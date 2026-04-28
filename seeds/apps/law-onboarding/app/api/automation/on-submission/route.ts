/**
 * POST /api/automation/on-submission
 *
 * Called internally (fire-and-forget) by the submit route after a new
 * intake_submission row is created.
 *
 * Workflow:
 *  1. Load the submission from DB
 *  2. Create Drive folder tree: /[LastName]_[FirstName]/Intake/ + /Redlines/
 *  3. Generate intake PDF and upload to /Intake/intake_form.pdf
 *  4. Upload client-provided docs to /Intake/
 *  5. Update submission: drive_folder_url, status → "Docs Received",
 *     uploaded_file_refs (with drive_url populated)
 *  6. Write audit log entry
 */
import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";
import { createClientFolderTree, uploadFile, decodeDataUrl } from "@/lib/google-drive";
import { generateIntakePdf } from "@/lib/pdf-generator";
import type { IntakeSubmission, FileRef } from "@/lib/types";

export const maxDuration = 60; // Allow up to 60 seconds for Drive ops

export async function POST(req: NextRequest) {
  // Internal-only: verify shared secret header to prevent external calls
  const secret = req.headers.get("x-automation-secret");
  const expected = process.env.NEXTAUTH_SECRET;
  if (!expected || secret !== expected) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  let submissionId: string;
  try {
    const body = await req.json();
    submissionId = body.submissionId;
    if (!submissionId) throw new Error("Missing submissionId");
  } catch {
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  // ── 1. Load submission ───────────────────────────────────────────────────
  const subResult = await query<IntakeSubmission>(
    `SELECT * FROM intake_submissions WHERE id = $1`,
    [submissionId]
  );

  if (subResult.rows.length === 0) {
    return NextResponse.json({ error: "Submission not found" }, { status: 404 });
  }

  const submission = subResult.rows[0];

  // Parse JSONB if returned as string
  if (typeof submission.uploaded_file_refs === "string") {
    submission.uploaded_file_refs = JSON.parse(submission.uploaded_file_refs);
  }

  try {
    // ── 2. Create Drive folder tree ────────────────────────────────────────
    const { clientFolderUrl, intakeFolderId, redlinesFolderId } =
      await createClientFolderTree(submission.last_name, submission.first_name);

    // Silence "unused" warning — redlinesFolderId reserved for Prompt 6
    void redlinesFolderId;

    // ── 3. Generate + upload intake PDF ────────────────────────────────────
    const pdfBuffer = await generateIntakePdf(submission);
    await uploadFile({
      name: "intake_form.pdf",
      mimeType: "application/pdf",
      buffer: pdfBuffer,
      parentId: intakeFolderId,
    });

    // ── 4. Upload client docs to /Intake/ ──────────────────────────────────
    const updatedRefs: FileRef[] = [];

    for (const fileRef of submission.uploaded_file_refs ?? []) {
      if (!fileRef.temp_data) {
        updatedRefs.push(fileRef);
        continue;
      }

      try {
        const { buffer, mime } = decodeDataUrl(fileRef.temp_data);
        const driveUrl = await uploadFile({
          name: fileRef.name,
          mimeType: mime,
          buffer,
          parentId: intakeFolderId,
        });

        updatedRefs.push({
          ...fileRef,
          drive_url: driveUrl,
          temp_data: undefined, // clear temp data after upload
        });
      } catch (uploadErr) {
        console.error(
          `[on-submission] Failed to upload ${fileRef.name}:`,
          uploadErr instanceof Error ? uploadErr.message : uploadErr
        );
        // Keep ref without drive_url; don't fail the whole automation
        updatedRefs.push({ ...fileRef, temp_data: undefined });
      }
    }

    // ── 5. Update submission row ───────────────────────────────────────────
    await query(
      `UPDATE intake_submissions
       SET
         drive_folder_url     = $1,
         status               = 'Docs Received',
         uploaded_file_refs   = $2::jsonb,
         needs_attention      = false
       WHERE id = $3`,
      [clientFolderUrl, JSON.stringify(updatedRefs), submissionId]
    );

    // ── 6. Audit log ───────────────────────────────────────────────────────
    await query(
      `INSERT INTO audit_log
         (submission_id, event_type, actor, from_status, to_status, detail)
       VALUES ($1, 'STATUS_CHANGE', 'system', 'New', 'Docs Received', $2::jsonb)`,
      [
        submissionId,
        JSON.stringify({
          note: "Google Drive folder created and files uploaded",
          drive_folder_url: clientFolderUrl,
          file_count: updatedRefs.length,
        }),
      ]
    );

    await query(
      `INSERT INTO audit_log
         (submission_id, event_type, actor, detail)
       VALUES ($1, 'DRIVE_OP', 'system', $2::jsonb)`,
      [
        submissionId,
        JSON.stringify({
          note: "Intake PDF generated and uploaded",
          intake_folder_id: intakeFolderId,
        }),
      ]
    );

    return NextResponse.json({ success: true, drive_folder_url: clientFolderUrl });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("[on-submission] Automation error:", message);

    // Flag needs_attention so attorney can see it in the dashboard
    await query(
      `UPDATE intake_submissions
       SET needs_attention = true
       WHERE id = $1`,
      [submissionId]
    ).catch(() => {/* best effort */});

    await query(
      `INSERT INTO audit_log
         (submission_id, event_type, actor, detail)
       VALUES ($1, 'DRIVE_OP', 'system', $2::jsonb)`,
      [
        submissionId,
        JSON.stringify({ error: message, note: "Automation failed — needs_attention set" }),
      ]
    ).catch(() => {/* best effort */});

    return NextResponse.json({ error: message }, { status: 500 });
  }
}
