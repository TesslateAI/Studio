/**
 * Legora API integration.
 *
 * Required env vars:
 *   LEGORA_API_KEY   – your Legora API key
 *   LEGORA_API_URL   – e.g. https://api.legora.io/v1
 *
 * Workflow per document:
 *  1. POST the document bytes + template to Legora /redline
 *  2. Receive redlined DOCX + confidence score
 *  3. Upload result to Drive /Redlines/[filename]_redlined.docx
 *  4. Update submission row: redline_file_refs, status, needs_attention
 *  5. Audit log each call
 */
import { query } from "@/lib/db";
import { uploadFile } from "@/lib/google-drive";
import { LEGORA_TEMPLATES, LEGORA_CONFIDENCE_THRESHOLD } from "@/config/templates";
import type { FileRef } from "@/lib/types";

export interface RunLegoraParams {
  submissionId: string;
  fileRefs: FileRef[];
  matterType: string;
  clientName: string;
  driveFolderUrl: string | null;
}

interface LegoraResponse {
  redlined_docx_base64: string;
  confidence: number;
  metadata?: Record<string, unknown>;
}

async function callLegoraApi(
  fileBuffer: Buffer,
  fileName: string,
  mimeType: string,
  templateId: string
): Promise<LegoraResponse> {
  const apiKey = process.env.LEGORA_API_KEY;
  const apiUrl = process.env.LEGORA_API_URL;

  if (!apiKey || !apiUrl) {
    throw new Error("LEGORA_API_KEY or LEGORA_API_URL not set");
  }

  const res = await fetch(`${apiUrl}/redline`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      document_base64: fileBuffer.toString("base64"),
      document_name: fileName,
      document_mime: mimeType,
      template_id: templateId,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Legora API error ${res.status}: ${text}`);
  }

  return res.json() as Promise<LegoraResponse>;
}

/** Get the Redlines sub-folder ID from drive given the client folder URL */
async function getRedlinesFolderId(clientFolderUrl: string): Promise<string | null> {
  try {
    // Extract folder ID from URL: .../folders/<id>
    const match = clientFolderUrl.match(/\/folders\/([a-zA-Z0-9_-]+)/);
    if (!match) return null;
    const clientFolderId = match[1];

    const { google } = await import("googleapis");
    const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
    if (!raw) return null;

    const auth = new google.auth.GoogleAuth({
      credentials: JSON.parse(raw),
      scopes: ["https://www.googleapis.com/auth/drive"],
    });
    const drive = google.drive({ version: "v3", auth });

    const res = await drive.files.list({
      q: `'${clientFolderId}' in parents and name = 'Redlines' and mimeType = 'application/vnd.google-apps.folder' and trashed = false`,
      fields: "files(id)",
      pageSize: 1,
    });

    return res.data.files?.[0]?.id ?? null;
  } catch {
    return null;
  }
}

export async function runLegora(params: RunLegoraParams): Promise<void> {
  const { submissionId, fileRefs, matterType, driveFolderUrl } = params;

  const templateId =
    LEGORA_TEMPLATES[matterType] ?? LEGORA_TEMPLATES["Other"];

  // Get Redlines folder
  const redlinesFolderId = driveFolderUrl
    ? await getRedlinesFolderId(driveFolderUrl)
    : null;

  const redlineRefs: FileRef[] = [];
  let hasLowConfidence = false;
  let allSucceeded = true;

  for (const fileRef of fileRefs) {
    if (!fileRef.drive_url && !fileRef.temp_data) {
      // Skip files we can't access
      continue;
    }

    let fileBuffer: Buffer;
    let mimeType: string;

    try {
      if (fileRef.temp_data) {
        // Parse data URL
        const match = fileRef.temp_data.match(/^data:([^;]+);base64,(.+)$/s);
        if (!match) throw new Error("Invalid temp_data format");
        mimeType = match[1];
        fileBuffer = Buffer.from(match[2], "base64");
      } else {
        // Fetch from Drive
        const driveRes = await fetch(fileRef.drive_url!);
        if (!driveRes.ok) throw new Error(`Drive fetch failed: ${driveRes.status}`);
        fileBuffer = Buffer.from(await driveRes.arrayBuffer());
        mimeType = fileRef.mime;
      }
    } catch (err) {
      console.error(`[legora] Failed to fetch file ${fileRef.name}:`, err);
      allSucceeded = false;

      await query(
        `INSERT INTO audit_log
           (submission_id, event_type, actor, detail)
         VALUES ($1, 'LEGORA_CALL', 'system', $2::jsonb)`,
        [
          submissionId,
          JSON.stringify({
            error: err instanceof Error ? err.message : "fetch failed",
            file: fileRef.name,
          }),
        ]
      );
      continue;
    }

    // Call Legora
    let legoraResult: LegoraResponse;
    try {
      legoraResult = await callLegoraApi(
        fileBuffer,
        fileRef.name,
        mimeType,
        templateId
      );
    } catch (err) {
      console.error(`[legora] API call failed for ${fileRef.name}:`, err);
      allSucceeded = false;

      await query(
        `INSERT INTO audit_log
           (submission_id, event_type, actor, detail)
         VALUES ($1, 'LEGORA_CALL', 'system', $2::jsonb)`,
        [
          submissionId,
          JSON.stringify({
            error: err instanceof Error ? err.message : "api error",
            file: fileRef.name,
            template: templateId,
          }),
        ]
      );
      continue;
    }

    // Check confidence
    if (legoraResult.confidence < LEGORA_CONFIDENCE_THRESHOLD) {
      hasLowConfidence = true;
    }

    // Upload redlined doc to Drive
    const redlinedName = fileRef.name.replace(/\.(docx|pdf)$/i, "") + "_redlined.docx";
    let driveUrl: string | undefined;

    if (redlinesFolderId) {
      try {
        const redlinedBuffer = Buffer.from(legoraResult.redlined_docx_base64, "base64");
        driveUrl = await uploadFile({
          name: redlinedName,
          mimeType:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          buffer: redlinedBuffer,
          parentId: redlinesFolderId,
        });
      } catch (err) {
        console.error(`[legora] Drive upload failed for ${redlinedName}:`, err);
        allSucceeded = false;
      }
    }

    redlineRefs.push({
      id: crypto.randomUUID(),
      name: redlinedName,
      size: 0,
      mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      drive_url: driveUrl,
      legora_confidence: legoraResult.confidence,
    });

    // Audit each Legora call
    await query(
      `INSERT INTO audit_log
         (submission_id, event_type, actor, detail)
       VALUES ($1, 'LEGORA_CALL', 'system', $2::jsonb)`,
      [
        submissionId,
        JSON.stringify({
          file: fileRef.name,
          template: templateId,
          confidence: legoraResult.confidence,
          output: redlinedName,
          drive_url: driveUrl ?? null,
        }),
      ]
    );
  }

  // Determine final status
  const needsAttention = hasLowConfidence || !allSucceeded;
  const finalStatus =
    redlineRefs.length > 0 ? "Ready for Review" : "Redlining";

  // Update submission
  await query(
    `UPDATE intake_submissions
     SET status = $1,
         redline_file_refs = $2::jsonb,
         needs_attention = $3
     WHERE id = $4`,
    [finalStatus, JSON.stringify(redlineRefs), needsAttention, submissionId]
  );

  // Final audit
  await query(
    `INSERT INTO audit_log
       (submission_id, event_type, actor, from_status, to_status, detail)
     VALUES ($1, 'STATUS_CHANGE', 'system', 'Redlining', $2, $3::jsonb)`,
    [
      submissionId,
      finalStatus,
      JSON.stringify({
        note: "Legora redline complete",
        docs_processed: redlineRefs.length,
        needs_attention: needsAttention,
      }),
    ]
  );
}
