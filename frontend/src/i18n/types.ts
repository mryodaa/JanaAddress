import type { FieldName } from "../api/client";

export type Language = "kk" | "ru" | "en";

export interface TranslationDictionary {
  // Navigation & General
  appTitle: string;
  navBatch: string;
  navCheck: string;
  serviceReady: string;
  serviceLoading: string;
  serviceTitle: string;
  serviceUnavailable: string;
  loading: string;

  // Upload screen
  dropTitle: string;
  dropHintPre: string;
  dropHintMid: string;
  dropHintPost: string;
  selectFile: string;
  uploadProgress: string; // e.g. "жүктелуде {pct}%"
  recentBatches: string;
  recordsCount: string; // e.g. "{total} жазба"

  // Check single address screen
  inputPlaceholder: string;
  parseButton: string;
  pipelineSteps: string;
  unparsed: string;

  // Session view
  searchPlaceholder: string;
  onlyUncertain: string;
  inList: string;
  shortcutsNav: string;
  shortcutsUncertain: string;
  shortcutsSave: string;
  exportJson: string;
  newFile: string;
  parsingInProgress: string;
  sessionNotFound: string;
  backToUpload: string;

  // Summary
  statRecords: string;
  statProcessed: string;
  statUncertain: string;
  statReviewed: string;
  showLink: string;
  avgConfidence: string;
  confidenceDist: string;
  confidenceHistogramAria: string;
  secondsFmt: string;
  parsingInProgressShort: string;

  // Table
  originalString: string;
  confidenceShort: string;
  nothingFound: string;

  // Editor
  recordTitle: string;
  positionOf: string;
  prevTooltip: string;
  nextTooltip: string;
  closeTooltip: string;
  saveAndNext: string;
  confirmAndNext: string;
  reviewedBadge: string;
  hideTrace: string;
  showTrace: string;

  // Sources & tags
  sourceManual: string;
  sourceRef: string;
  sourceManualTooltip: string;
  sourceRefTooltip: string;
  sourceRefBase: string;
  msUnit: string;

  // Field labels
  fields: Record<FieldName, string>;

  // Pipeline step names
  steps: Record<string, string>;
}

export type TranslationKey = keyof Omit<TranslationDictionary, "fields" | "steps">;

export interface AvailableLanguage {
  code: Language;
  label: string;
  short: string;
  locale: string;
}
