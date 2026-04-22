"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

export default function ConfirmationContent() {
  const searchParams = useSearchParams();
  const submissionId = searchParams.get("id");
  const [copied, setCopied] = useState(false);

  const shortId = submissionId ? submissionId.slice(0, 8).toUpperCase() : null;

  const handleCopy = () => {
    if (shortId) {
      navigator.clipboard.writeText(shortId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <div className="max-w-lg w-full">
        {/* Success card */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-8 text-center">
          {/* Checkmark */}
          <div className="w-16 h-16 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-6">
            <svg
              className="w-8 h-8 text-emerald-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>

          <h1 className="text-2xl font-semibold text-slate-900 mb-2">
            Submission Received
          </h1>
          <p className="text-slate-500 mb-8">
            Thank you for reaching out. Our team will review your matter and
            be in touch within 1–2 business days.
          </p>

          {/* Reference number */}
          {shortId && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-8">
              <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">
                Your Reference Number
              </p>
              <div className="flex items-center justify-center gap-3">
                <span className="text-xl font-mono font-semibold text-slate-900">
                  {shortId}
                </span>
                <button
                  onClick={handleCopy}
                  className="text-slate-400 hover:text-slate-700 transition-colors"
                  title="Copy reference number"
                >
                  {copied ? (
                    <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  )}
                </button>
              </div>
              <p className="text-xs text-slate-400 mt-2">
                Keep this number for your records
              </p>
            </div>
          )}

          {/* What happens next */}
          <div className="text-left mb-8">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">
              What happens next
            </h2>
            <ul className="space-y-2">
              {[
                "Our team reviews your submission and documents",
                "An attorney is assigned to your matter",
                "We'll contact you to schedule a consultation",
              ].map((step, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-slate-600">
                  <span className="w-5 h-5 rounded-full bg-slate-200 text-slate-600 flex items-center justify-center text-xs font-semibold flex-shrink-0 mt-0.5">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ul>
          </div>

          <Link
            href="/"
            className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
          >
            ← Submit another matter
          </Link>
        </div>

        {/* Footer note */}
        <p className="text-center text-xs text-slate-400 mt-6">
          If you have an urgent matter, please call our office directly.
        </p>
      </div>
    </div>
  );
}
