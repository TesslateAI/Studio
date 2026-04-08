package btrfs

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"io"
	"testing"
)

// buildSendStream constructs a minimal btrfs send stream for testing.
func buildSendStream(cmdType uint16, tlvs []tlvEntry) []byte {
	var buf bytes.Buffer

	// Stream header: magic + version.
	buf.WriteString(sendStreamMagic)
	binary.Write(&buf, binary.LittleEndian, uint32(1)) // version 1

	// Build TLV payload.
	var payload bytes.Buffer
	for _, tlv := range tlvs {
		binary.Write(&payload, binary.LittleEndian, tlv.typ)
		binary.Write(&payload, binary.LittleEndian, uint16(len(tlv.data)))
		payload.Write(tlv.data)
	}

	// Command header: len + cmd + crc (placeholder).
	payloadBytes := payload.Bytes()
	cmdHdr := make([]byte, cmdHeaderLen)
	binary.LittleEndian.PutUint32(cmdHdr[0:4], uint32(len(payloadBytes)))
	binary.LittleEndian.PutUint16(cmdHdr[4:6], cmdType)
	binary.LittleEndian.PutUint32(cmdHdr[6:10], 0) // crc placeholder

	// Compute CRC.
	combined := append(cmdHdr, payloadBytes...)
	crc := sendCRC32C(combined)
	binary.LittleEndian.PutUint32(cmdHdr[6:10], crc)

	buf.Write(cmdHdr)
	buf.Write(payloadBytes)
	return buf.Bytes()
}

type tlvEntry struct {
	typ  uint16
	data []byte
}

func uuidBytes(s string) []byte {
	b, _ := hex.DecodeString(s)
	return b
}

func uint64Bytes(v uint64) []byte {
	b := make([]byte, 8)
	binary.LittleEndian.PutUint64(b, v)
	return b
}

func TestRewriteParentUUID_Snapshot(t *testing.T) {
	origUUID := "aabbccdd11223344aabbccdd11223344"
	origCT := uint64(42)

	stream := buildSendStream(cmdSnapshot, []tlvEntry{
		{15, []byte("test-snap")},                     // BTRFS_SEND_A_PATH
		{1, uuidBytes("00112233445566778899aabbccddeeff")}, // BTRFS_SEND_A_UUID
		{2, uint64Bytes(100)},                         // BTRFS_SEND_A_CTRANSID
		{attrCloneUUID, uuidBytes(origUUID)},          // parent UUID
		{attrCloneCtransid, uint64Bytes(origCT)},      // parent ctransid
	})

	newParent := SubvolumeIdentity{
		Ctransid: 99,
	}
	copy(newParent.UUID[:], uuidBytes("ffeeddccbbaa99887766554433221100"))

	reader := RewriteParentUUID(bytes.NewReader(stream), newParent)
	result, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("RewriteParentUUID: %v", err)
	}

	// Verify the stream is valid (same overall structure).
	if len(result) != len(stream) {
		t.Fatalf("length mismatch: got %d, want %d", len(result), len(stream))
	}

	// Parse the result to verify UUID was rewritten.
	off := streamHeaderLen + cmdHeaderLen // skip stream header + cmd header
	for off+4 <= len(result) {
		tlvType := binary.LittleEndian.Uint16(result[off : off+2])
		tlvLen := int(binary.LittleEndian.Uint16(result[off+2 : off+4]))
		dataStart := off + 4
		dataEnd := dataStart + tlvLen
		if dataEnd > len(result) {
			break
		}

		if tlvType == attrCloneUUID {
			got := hex.EncodeToString(result[dataStart:dataEnd])
			want := "ffeeddccbbaa99887766554433221100"
			if got != want {
				t.Errorf("CLONE_UUID: got %s, want %s", got, want)
			}
		}
		if tlvType == attrCloneCtransid {
			got := binary.LittleEndian.Uint64(result[dataStart:dataEnd])
			if got != 99 {
				t.Errorf("CLONE_CTRANSID: got %d, want 99", got)
			}
		}
		off = dataEnd
	}

	// Verify CRC is valid.
	cmdStart := streamHeaderLen
	payloadLen := binary.LittleEndian.Uint32(result[cmdStart : cmdStart+4])
	storedCRC := binary.LittleEndian.Uint32(result[cmdStart+6 : cmdStart+10])

	check := make([]byte, cmdHeaderLen+payloadLen)
	copy(check, result[cmdStart:cmdStart+cmdHeaderLen+int(payloadLen)])
	binary.LittleEndian.PutUint32(check[6:10], 0)
	computed := sendCRC32C(check)
	if computed != storedCRC {
		t.Errorf("CRC mismatch: stored=0x%08x computed=0x%08x", storedCRC, computed)
	}
}

func TestRewriteParentUUID_FullSend(t *testing.T) {
	// Full send uses SUBVOL (type 1), not SNAPSHOT — no CLONE_UUID.
	// The rewriter should pass it through unchanged.
	stream := buildSendStream(1, []tlvEntry{ // BTRFS_SEND_C_SUBVOL
		{15, []byte("test-subvol")},
		{1, uuidBytes("00112233445566778899aabbccddeeff")},
		{2, uint64Bytes(100)},
	})

	newParent := SubvolumeIdentity{Ctransid: 99}
	copy(newParent.UUID[:], uuidBytes("ffeeddccbbaa99887766554433221100"))

	reader := RewriteParentUUID(bytes.NewReader(stream), newParent)
	result, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("RewriteParentUUID: %v", err)
	}

	// Should be byte-identical (no CLONE_UUID to rewrite).
	if !bytes.Equal(result, stream) {
		t.Error("full send stream should pass through unchanged")
	}
}

func TestRewriteParentUUID_MultipleCommands(t *testing.T) {
	// Build a stream with SNAPSHOT + a WRITE command (type 15, no UUID).
	var buf bytes.Buffer
	buf.WriteString(sendStreamMagic)
	binary.Write(&buf, binary.LittleEndian, uint32(1))

	// SNAPSHOT command.
	snapTLVs := []tlvEntry{
		{15, []byte("snap")},
		{attrCloneUUID, uuidBytes("aaaa000000000000aaaa000000000000")},
		{attrCloneCtransid, uint64Bytes(10)},
	}
	var snapPayload bytes.Buffer
	for _, tlv := range snapTLVs {
		binary.Write(&snapPayload, binary.LittleEndian, tlv.typ)
		binary.Write(&snapPayload, binary.LittleEndian, uint16(len(tlv.data)))
		snapPayload.Write(tlv.data)
	}
	snapBytes := snapPayload.Bytes()
	snapHdr := make([]byte, cmdHeaderLen)
	binary.LittleEndian.PutUint32(snapHdr[0:4], uint32(len(snapBytes)))
	binary.LittleEndian.PutUint16(snapHdr[4:6], cmdSnapshot)
	binary.LittleEndian.PutUint32(snapHdr[6:10], 0)
	combined := append(snapHdr, snapBytes...)
	binary.LittleEndian.PutUint32(snapHdr[6:10], sendCRC32C(combined))
	buf.Write(snapHdr)
	buf.Write(snapBytes)

	// WRITE command (type 15 = BTRFS_SEND_C_SET_XATTR, used as generic non-UUID cmd).
	writeData := []byte("hello world this is file data")
	writeHdr := make([]byte, cmdHeaderLen)
	binary.LittleEndian.PutUint32(writeHdr[0:4], uint32(len(writeData)))
	binary.LittleEndian.PutUint16(writeHdr[4:6], 15)
	binary.LittleEndian.PutUint32(writeHdr[6:10], 0)
	combined2 := append(writeHdr, writeData...)
	binary.LittleEndian.PutUint32(writeHdr[6:10], sendCRC32C(combined2))
	origWriteCRC := binary.LittleEndian.Uint32(writeHdr[6:10])
	buf.Write(writeHdr)
	buf.Write(writeData)

	stream := buf.Bytes()

	newParent := SubvolumeIdentity{Ctransid: 77}
	copy(newParent.UUID[:], uuidBytes("bbbb111111111111bbbb111111111111"))

	reader := RewriteParentUUID(bytes.NewReader(stream), newParent)
	result, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("RewriteParentUUID: %v", err)
	}

	if len(result) != len(stream) {
		t.Fatalf("length mismatch: got %d, want %d", len(result), len(stream))
	}

	// Second command (WRITE) should be unchanged.
	snapSize := cmdHeaderLen + len(snapBytes)
	writeOffset := streamHeaderLen + snapSize
	resultWriteCRC := binary.LittleEndian.Uint32(result[writeOffset+6 : writeOffset+10])
	if resultWriteCRC != origWriteCRC {
		t.Errorf("WRITE command CRC changed: got 0x%08x, want 0x%08x", resultWriteCRC, origWriteCRC)
	}
}
