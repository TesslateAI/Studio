"use client";

import { useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";

type MatterType = "NDA" | "Contractor Agreement" | "Confidentiality" | "Employment Contract" | "Commercial Lease" | "SaaS Agreement" | "IP Assignment" | "Joint Venture" | "Other";

interface FormState {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  matter_type: MatterType | "";
  description: string;
  consent: boolean;
}

interface FileWithPreview {
  file: File;
  id: string;
  error?: string;
}

const MATTER_TYPES: MatterType[] = [
  "NDA",
  "Contractor Agreement",
  "Confidentiality",
  "Employment Contract",
  "Commercial Lease",
  "SaaS Agreement",
  "IP Assignment",
  "Joint Venture",
  "Other",
];

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
const ALLOWED_MIME = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const ALLOWED_EXT = [".pdf", ".docx"];

function generateId() {
  return Math.random().toString(36).slice(2, 9);
}

export default function IntakePage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState<FormState>({
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    matter_type: "",
    description: "",
    consent: false,
  });

  const [files, setFiles] = useState<FileWithPreview[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof FormState, string>>>({});

  // --- Handlers ---

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;
    setForm((prev) => ({
      ...prev,
      [name]: type === "checkbox" ? checked : value,
    }));
    // Clear field error on change
    if (fieldErrors[name as keyof FormState]) {
      setFieldErrors((prev) => ({ ...prev, [name]: undefined }));
    }
  };

  const validateFile = (file: File): string | undefined => {
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_EXT.includes(ext) && !ALLOWED_MIME.includes(file.type)) {
      return "Only PDF and DOCX files are allowed";
    }
    if (file.size > MAX_FILE_SIZE) {
      return "File must be under 10MB";
    }
    return undefined;
  };

  const addFiles = useCallback((incoming: File[]) => {
    const newFiles: FileWithPreview[] = incoming.map((file) => ({
      file,
      id: generateId(),
      error: validateFile(file),
    }));
    setFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const removeFile = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => setIsDragging(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  };

  // --- Validation ---

  const validate = (): boolean => {
    const errors: Partial<Record<keyof FormState, string>> = {};
    if (!form.first_name.trim()) errors.first_name = "First name is required";
    if (!form.last_name.trim()) errors.last_name = "Last name is required";
    if (!form.email.trim()) {
      errors.email = "Email is required";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      errors.email = "Enter a valid email address";
    }
    if (!form.matter_type) errors.matter_type = "Please select a matter type";
    if (!form.description.trim() || form.description.trim().length < 20) {
      errors.description = "Please provide at least 20 characters describing your matter";
    }
    if (!form.consent) errors.consent = "You must acknowledge the consent statement";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // --- Submit ---

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);

    if (!validate()) return;

    const hasFileErrors = files.some((f) => f.error);
    if (hasFileErrors) {
      setSubmitError("Please remove files with errors before submitting.");
      return;
    }

    setIsSubmitting(true);

    try {
      const formData = new FormData();
      Object.entries(form).forEach(([key, value]) => {
        formData.append(key, String(value));
      });
      files.forEach(({ file }) => {
        formData.append("files", file, file.name);
      });

      const res = await fetch("/api/submit", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        setSubmitError(data.error ?? "Something went wrong. Please try again.");
        setIsSubmitting(false);
        return;
      }

      router.push(`/confirmation?id=${data.id}`);
    } catch {
      setSubmitError("Network error. Please check your connection and try again.");
      setIsSubmitting(false);
    }
  };

  // --- Render ---

  return (
    <div className="min-h-screen bg-slate-50 py-12 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-semibold text-slate-900">
            Legal Matter Intake
          </h1>
          <p className="text-slate-500 mt-2">
            Complete the form below to submit your matter for review. All
            information is confidential.
          </p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          {/* Personal Information */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-4">
            <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-5">
              Contact Information
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field
                label="First Name"
                required
                error={fieldErrors.first_name}
              >
                <input
                  name="first_name"
                  value={form.first_name}
                  onChange={handleChange}
                  className={inputClass(!!fieldErrors.first_name)}
                  placeholder="Jane"
                  autoComplete="given-name"
                />
              </Field>

              <Field
                label="Last Name"
                required
                error={fieldErrors.last_name}
              >
                <input
                  name="last_name"
                  value={form.last_name}
                  onChange={handleChange}
                  className={inputClass(!!fieldErrors.last_name)}
                  placeholder="Smith"
                  autoComplete="family-name"
                />
              </Field>

              <Field label="Email Address" required error={fieldErrors.email}>
                <input
                  name="email"
                  type="email"
                  value={form.email}
                  onChange={handleChange}
                  className={inputClass(!!fieldErrors.email)}
                  placeholder="jane@example.com"
                  autoComplete="email"
                />
              </Field>

              <Field label="Phone Number" error={fieldErrors.phone}>
                <input
                  name="phone"
                  type="tel"
                  value={form.phone}
                  onChange={handleChange}
                  className={inputClass(false)}
                  placeholder="+1 (555) 000-0000"
                  autoComplete="tel"
                />
              </Field>
            </div>
          </div>

          {/* Matter Details */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-4">
            <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-5">
              Matter Details
            </h2>

            <div className="space-y-4">
              <Field
                label="Matter Type"
                required
                error={fieldErrors.matter_type}
              >
                <select
                  name="matter_type"
                  value={form.matter_type}
                  onChange={handleChange}
                  className={inputClass(!!fieldErrors.matter_type)}
                >
                  <option value="">Select a matter type…</option>
                  {MATTER_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </Field>

              <Field
                label="Description"
                required
                error={fieldErrors.description}
                hint="Briefly describe the matter you need assistance with."
              >
                <textarea
                  name="description"
                  value={form.description}
                  onChange={handleChange}
                  rows={4}
                  className={inputClass(!!fieldErrors.description) + " resize-none"}
                  placeholder="Please describe your legal matter in detail…"
                />
              </Field>
            </div>
          </div>

          {/* File Upload */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-4">
            <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-1">
              Documents
            </h2>
            <p className="text-xs text-slate-400 mb-5">
              Optional. Upload relevant documents (.pdf or .docx, max 10MB each).
            </p>

            {/* Drop zone */}
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              aria-label="Upload documents — click or drag and drop PDF or DOCX files"
              onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                isDragging
                  ? "border-blue-400 bg-blue-50"
                  : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx"
                onChange={handleFileInput}
                className="hidden"
              />
              <svg
                className="w-8 h-8 text-slate-300 mx-auto mb-2"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.338-2.32 5.75 5.75 0 011.572 9.095"
                />
              </svg>
              <p className="text-sm text-slate-500">
                <span className="text-blue-600 font-medium">Click to upload</span>{" "}
                or drag and drop
              </p>
              <p className="text-xs text-slate-400 mt-1">PDF, DOCX up to 10MB</p>
            </div>

            {/* File list */}
            {files.length > 0 && (
              <ul className="mt-3 space-y-2">
                {files.map(({ file, id, error }) => (
                  <li
                    key={id}
                    className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm ${
                      error ? "bg-red-50 border border-red-200" : "bg-slate-50 border border-slate-200"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <FileIcon mime={file.type} />
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-700">
                          {file.name}
                        </p>
                        {error ? (
                          <p className="text-red-500 text-xs">{error}</p>
                        ) : (
                          <p className="text-slate-400 text-xs">
                            {formatBytes(file.size)}
                          </p>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(id)}
                      className="text-slate-400 hover:text-red-500 transition-colors flex-shrink-0 ml-2"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Consent */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-6">
            <label className={`flex items-start gap-3 cursor-pointer ${fieldErrors.consent ? "text-red-600" : ""}`}>
              <div className="relative flex-shrink-0 mt-0.5">
                <input
                  name="consent"
                  type="checkbox"
                  checked={form.consent}
                  onChange={handleChange}
                  className="sr-only"
                />
                <div
                  className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                    form.consent
                      ? "bg-blue-600 border-blue-600"
                      : fieldErrors.consent
                      ? "border-red-400 bg-white"
                      : "border-slate-300 bg-white"
                  }`}
                >
                  {form.consent && (
                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
              </div>
              <span className="text-sm text-slate-600 leading-snug">
                I consent to the collection and use of the information provided
                above for the purpose of evaluating my legal matter. I
                understand this submission does not create an attorney-client
                relationship.{" "}
                <span className="text-red-500">*</span>
              </span>
            </label>
            {fieldErrors.consent && (
              <p className="text-red-500 text-xs mt-2 ml-8">{fieldErrors.consent}</p>
            )}
          </div>

          {/* Submit error */}
          {submitError && (
            <div className="mb-4 rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {submitError}
            </div>
          )}

          {/* Submit button */}
          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-3 px-6 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold rounded-xl transition-colors shadow-sm"
          >
            {isSubmitting ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Submitting…
              </span>
            ) : (
              "Submit Matter"
            )}
          </button>

          <p className="text-center text-xs text-slate-400 mt-4">
            Your information is encrypted and kept strictly confidential.
          </p>
        </form>
      </div>
    </div>
  );
}

// --- Sub-components ---

function Field({
  label,
  required,
  error,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {children}
      {hint && !error && (
        <p className="text-xs text-slate-400 mt-1">{hint}</p>
      )}
      {error && <p className="text-xs text-red-500 mt-1">{error}</p>}
    </div>
  );
}

function FileIcon({ mime }: { mime: string }) {
  const isPdf = mime === "application/pdf";
  return (
    <div
      className={`w-7 h-7 rounded flex items-center justify-center text-xs font-bold flex-shrink-0 ${
        isPdf ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"
      }`}
    >
      {isPdf ? "PDF" : "DOC"}
    </div>
  );
}

function inputClass(hasError: boolean) {
  return `w-full rounded-lg border px-3 py-2 text-sm text-slate-900 outline-none transition-colors
    ${
      hasError
        ? "border-red-400 focus:border-red-500 focus:ring-2 focus:ring-red-100"
        : "border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
    }`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
