/**
 * Google Drive helpers using a Service Account.
 *
 * Required env vars:
 *   GOOGLE_SERVICE_ACCOUNT_JSON  – full JSON key as a string
 *   GOOGLE_DRIVE_ROOT_FOLDER_ID  – parent folder for all clients
 */
import { google } from "googleapis";
import { Readable } from "stream";

function getDriveClient() {
  const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!raw) throw new Error("GOOGLE_SERVICE_ACCOUNT_JSON is not set");

  let creds: Record<string, unknown>;
  try {
    creds = JSON.parse(raw);
  } catch {
    throw new Error("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON");
  }

  const auth = new google.auth.GoogleAuth({
    credentials: creds,
    scopes: ["https://www.googleapis.com/auth/drive"],
  });

  return google.drive({ version: "v3", auth });
}

/** Create a folder under a given parent. Returns the new folder ID. */
export async function createFolder(
  name: string,
  parentId: string
): Promise<string> {
  const drive = getDriveClient();
  const res = await drive.files.create({
    requestBody: {
      name,
      mimeType: "application/vnd.google-apps.folder",
      parents: [parentId],
    },
    fields: "id",
  });
  const id = res.data.id;
  if (!id) throw new Error(`Failed to create folder "${name}"`);
  return id;
}

/** Upload a buffer to Drive. Returns the file's web-view URL. */
export async function uploadFile({
  name,
  mimeType,
  buffer,
  parentId,
}: {
  name: string;
  mimeType: string;
  buffer: Buffer;
  parentId: string;
}): Promise<string> {
  const drive = getDriveClient();
  const stream = Readable.from(buffer);

  const res = await drive.files.create({
    requestBody: {
      name,
      parents: [parentId],
    },
    media: {
      mimeType,
      body: stream,
    },
    fields: "id,webViewLink",
  });

  const url = res.data.webViewLink;
  if (!url) throw new Error(`Failed to upload file "${name}"`);
  return url;
}

/**
 * Build the full folder structure for a client submission.
 * Returns { clientFolderUrl, intakeFolderId, redlinesFolderId }
 */
export async function createClientFolderTree(
  lastName: string,
  firstName: string
): Promise<{
  clientFolderUrl: string;
  intakeFolderId: string;
  redlinesFolderId: string;
}> {
  const rootId = process.env.GOOGLE_DRIVE_ROOT_FOLDER_ID;
  if (!rootId) throw new Error("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set");

  const drive = getDriveClient();

  // /Clients/[LastName]_[FirstName]/
  const clientFolderName = `${lastName}_${firstName}`;
  const clientFolderId = await createFolder(clientFolderName, rootId);

  // Fetch web link for the client folder
  const meta = await drive.files.get({
    fileId: clientFolderId,
    fields: "webViewLink",
  });
  const clientFolderUrl = meta.data.webViewLink ?? `https://drive.google.com/drive/folders/${clientFolderId}`;

  // Subfolders
  const intakeFolderId = await createFolder("Intake", clientFolderId);
  const redlinesFolderId = await createFolder("Redlines", clientFolderId);

  return { clientFolderUrl, intakeFolderId, redlinesFolderId };
}

/** Decode a temp_data base64 data URL back to a Buffer + mime */
export function decodeDataUrl(dataUrl: string): { buffer: Buffer; mime: string } {
  const match = dataUrl.match(/^data:([^;]+);base64,(.+)$/s);
  if (!match) throw new Error("Invalid data URL");
  const [, mime, b64] = match;
  return { buffer: Buffer.from(b64, "base64"), mime };
}
