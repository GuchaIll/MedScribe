import { useEffect, useSyncExternalStore } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { getSessionRecord } from "@/api";
import { useSession } from "@/hooks/useSession";
import { LeftRail } from "@/components/clinical/LeftRail";
import {
  DocumentViewer,
  type DocumentViewerDoc,
} from "@/components/ocr/DocumentViewer";
import {
  getCachedDocument,
  subscribeDocumentCache,
  type CachedDocument,
} from "@/components/ocr/documentCache";
import type { StructuredRecord } from "@/lib/clinical";

const useCachedDocument = (filename: string): CachedDocument | undefined => {
  return useSyncExternalStore(
    (cb) => subscribeDocumentCache(cb),
    () => getCachedDocument(filename),
    () => getCachedDocument(filename),
  );
};

const DocumentReview = () => {
  const { docId } = useParams<{ docId: string }>();
  const navigate = useNavigate();
  const { sessionId } = useSession();

  const decoded = docId ? decodeURIComponent(docId) : "";
  const cached = useCachedDocument(decoded);

  // Live consolidated record from the backend — useful when the cache is cold
  // (the user landed on this page from a refresh) or when other surfaces have
  // merged new data into the session record.
  const { data: sessionRecord } = useQuery({
    queryKey: ["session", sessionId, "record"],
    queryFn: () => (sessionId ? getSessionRecord(sessionId) : Promise.resolve(null)),
    enabled: !!sessionId,
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (!docId) navigate("/", { replace: true });
  }, [docId, navigate]);

  const doc: DocumentViewerDoc = {
    documentId: decoded,
    name: cached?.filename ?? decoded,
    type: cached?.content_type,
    documentType: cached?.document_type ?? cached?.content_type,
    confidence:
      typeof cached?.overall_confidence === "number"
        ? Math.round(cached.overall_confidence * 100)
        : undefined,
    status: cached?.status ?? "Pending",
    previewUrl: cached?.previewUrl,
    fieldChanges: cached?.field_changes,
  };

  // Prefer the live session record (kept fresh by react-query), but fall back
  // to the snapshot the upload response gave us so the form is populated
  // immediately on landing.
  const structuredRecord: StructuredRecord | null =
    sessionRecord?.structured_record ?? cached?.structured_record ?? null;

  return (
    <main className="relative min-h-screen w-full overflow-hidden p-2 md:p-4">
      <div className="pointer-events-none absolute -top-32 -right-20 h-[420px] w-[420px] rounded-full bg-gradient-to-br from-[hsl(38_100%_80%/0.5)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-[420px] w-[420px] rounded-full bg-gradient-to-tr from-[hsl(220_100%_82%/0.55)] to-transparent blur-3xl" />

      <div className="relative mx-auto flex h-[calc(100vh-1rem)] max-w-[1480px] overflow-hidden rounded-[2.25rem] glass-panel md:h-[calc(100vh-2rem)]">
        <LeftRail />
        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex shrink-0 items-center gap-3 border-b border-foreground/10 bg-white/60 px-6 py-3 backdrop-blur-md">
            <button
              type="button"
              onClick={() => navigate(-1)}
              aria-label="Back"
              className="glass-chip flex h-8 w-8 items-center justify-center rounded-full text-foreground/70 hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
            </button>
            <div className="min-w-0">
              <div className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-foreground/45">
                Document review
              </div>
              <div className="truncate text-[14px] font-semibold">{doc.name}</div>
            </div>
            {cached?.agent_summary && (
              <p className="ml-4 line-clamp-2 max-w-[520px] text-[11.5px] text-foreground/55">
                {cached.agent_summary}
              </p>
            )}
          </header>
          <div className="min-h-0 flex-1">
            <DocumentViewer
              doc={doc}
              structuredRecord={structuredRecord}
              onBack={() => navigate(-1)}
              onSave={(rec) => {
                // Phase 4 will wire this to the backend record endpoint.
                console.info("Record save requested", rec);
              }}
            />
          </div>
        </section>
      </div>
    </main>
  );
};

export default DocumentReview;
