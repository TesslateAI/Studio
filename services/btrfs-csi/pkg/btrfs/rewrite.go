package btrfs

import (
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"io"
)

// Send stream constants from the btrfs on-disk format.
const (
	sendStreamMagic = "btrfs-stream\x00"
	streamHeaderLen = 17 // 13-byte magic + 4-byte version (LE32)
	cmdHeaderLen    = 10 // 4-byte len + 2-byte cmd + 4-byte crc

	// Command types that carry parent UUID references.
	cmdSnapshot = 2
	cmdClone    = 22

	// TLV attribute types for parent identification.
	attrCloneUUID     = 20 // 16-byte UUID of the parent subvolume
	attrCloneCtransid = 21 // 8-byte creation transid of the parent
)

var crc32cTab = crc32.MakeTable(crc32.Castagnoli)

// sendCRC32C computes btrfs's standard CRC32C (seed 0xFFFFFFFF, final XOR).
func sendCRC32C(data []byte) uint32 {
	return crc32.Update(0xFFFFFFFF, crc32cTab, data) ^ 0xFFFFFFFF
}

// SubvolumeIdentity holds the UUID and creation transid of a btrfs subvolume,
// used to rewrite parent references in send streams.
type SubvolumeIdentity struct {
	UUID     [16]byte
	Ctransid uint64
}

// RewriteParentUUID returns an io.Reader that wraps a btrfs send stream,
// rewriting the parent UUID and ctransid in SNAPSHOT and CLONE commands to
// match the given local parent identity. All other commands pass through
// unchanged. This decouples btrfs receive from kernel-assigned UUIDs,
// enabling content-hash-based layer identity.
//
// The rewriter operates in constant memory (one command buffer at a time)
// and is safe for streaming (pipe btrfs send | rewrite | btrfs receive).
func RewriteParentUUID(src io.Reader, parent SubvolumeIdentity) io.Reader {
	pr, pw := io.Pipe()
	go func() {
		pw.CloseWithError(rewriteStream(src, pw, parent))
	}()
	return pr
}

func rewriteStream(r io.Reader, w io.Writer, parent SubvolumeIdentity) error {
	// Pass through the 17-byte stream header unchanged.
	hdr := make([]byte, streamHeaderLen)
	if _, err := io.ReadFull(r, hdr); err != nil {
		return fmt.Errorf("read stream header: %w", err)
	}
	if string(hdr[:13]) != sendStreamMagic {
		return fmt.Errorf("invalid btrfs send stream magic")
	}
	if _, err := w.Write(hdr); err != nil {
		return err
	}

	for {
		// Read 10-byte command header.
		cmdHdr := make([]byte, cmdHeaderLen)
		if _, err := io.ReadFull(r, cmdHdr); err != nil {
			if err == io.EOF || err == io.ErrUnexpectedEOF {
				return nil // end of stream
			}
			return fmt.Errorf("read command header: %w", err)
		}

		payloadLen := binary.LittleEndian.Uint32(cmdHdr[0:4])
		cmdType := binary.LittleEndian.Uint16(cmdHdr[4:6])

		payload := make([]byte, payloadLen)
		if payloadLen > 0 {
			if _, err := io.ReadFull(r, payload); err != nil {
				return fmt.Errorf("read payload (%d bytes): %w", payloadLen, err)
			}
		}

		// Rewrite parent references in SNAPSHOT and CLONE commands.
		if cmdType == cmdSnapshot || cmdType == cmdClone {
			if patchCloneTLV(payload, parent) {
				// Recompute CRC: zero the crc field, hash header+payload.
				binary.LittleEndian.PutUint32(cmdHdr[6:10], 0)
				buf := make([]byte, cmdHeaderLen+len(payload))
				copy(buf, cmdHdr)
				copy(buf[cmdHeaderLen:], payload)
				binary.LittleEndian.PutUint32(cmdHdr[6:10], sendCRC32C(buf))
			}
		}

		if _, err := w.Write(cmdHdr); err != nil {
			return err
		}
		if len(payload) > 0 {
			if _, err := w.Write(payload); err != nil {
				return err
			}
		}
	}
}

// patchCloneTLV walks TLV attributes in a command payload and replaces
// CLONE_UUID and CLONE_CTRANSID with the given identity. Returns true
// if any replacement was made.
func patchCloneTLV(payload []byte, id SubvolumeIdentity) bool {
	patched := false
	off := 0
	for off+4 <= len(payload) {
		tlvType := binary.LittleEndian.Uint16(payload[off : off+2])
		tlvLen := int(binary.LittleEndian.Uint16(payload[off+2 : off+4]))
		dataStart := off + 4
		dataEnd := dataStart + tlvLen
		if dataEnd > len(payload) {
			break
		}
		if tlvType == attrCloneUUID && tlvLen == 16 {
			copy(payload[dataStart:dataEnd], id.UUID[:])
			patched = true
		} else if tlvType == attrCloneCtransid && tlvLen == 8 {
			binary.LittleEndian.PutUint64(payload[dataStart:dataEnd], id.Ctransid)
			patched = true
		}
		off = dataEnd
	}
	return patched
}
