import { Suspense } from "react";
import ConfirmationContent from "./ConfirmationContent";

export const metadata = {
  title: "Submission Confirmed",
};

export default function ConfirmationPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-50 flex items-center justify-center">
          <div className="text-slate-400 text-sm">Loading…</div>
        </div>
      }
    >
      <ConfirmationContent />
    </Suspense>
  );
}
