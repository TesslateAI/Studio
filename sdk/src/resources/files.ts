import type { HttpClient } from "../http.js";
import type {
  FileBatchReadResult,
  FileDeleteResult,
  FileMkdirResult,
  FileReadResult,
  FileRenameResult,
  FileTreeResult,
  FileWriteResult,
} from "../types.js";

export class FilesResource {
  constructor(
    private readonly http: HttpClient,
    private readonly slug: string,
  ) {}

  /** Get the file tree for the project. */
  async tree(containerDir?: string): Promise<FileTreeResult> {
    const query: Record<string, string> = {};
    if (containerDir) query.container_dir = containerDir;
    return this.http.get(`/api/projects/${this.slug}/files/tree`, query);
  }

  /** Read a single file. */
  async read(path: string, containerDir?: string): Promise<FileReadResult> {
    const query: Record<string, string> = { path };
    if (containerDir) query.container_dir = containerDir;
    return this.http.get(`/api/projects/${this.slug}/files/content`, query);
  }

  /** Read multiple files in one request. */
  async readBatch(paths: string[], containerDir?: string): Promise<FileBatchReadResult> {
    const body: Record<string, unknown> = { paths };
    if (containerDir) body.container_dir = containerDir;
    return this.http.post(`/api/projects/${this.slug}/files/content/batch`, body);
  }

  /** Write content to a file (creates or overwrites). */
  async write(filePath: string, content: string): Promise<FileWriteResult> {
    return this.http.post(`/api/projects/${this.slug}/files/save`, {
      file_path: filePath,
      content,
    });
  }

  /** Delete a file or directory. */
  async delete(filePath: string, isDirectory = false): Promise<FileDeleteResult> {
    return this.http.delete(`/api/projects/${this.slug}/files`, {
      file_path: filePath,
      is_directory: isDirectory,
    });
  }

  /** Rename or move a file. */
  async rename(oldPath: string, newPath: string): Promise<FileRenameResult> {
    return this.http.post(`/api/projects/${this.slug}/files/rename`, {
      old_path: oldPath,
      new_path: newPath,
    });
  }

  /** Create a directory. */
  async mkdir(dirPath: string): Promise<FileMkdirResult> {
    return this.http.post(`/api/projects/${this.slug}/files/mkdir`, {
      dir_path: dirPath,
    });
  }
}
