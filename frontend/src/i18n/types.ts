import type { FieldName } from "../api/client";

export type Language = "kk" | "ru" | "en";

export interface TranslationDictionary {
  // Navigation & General
  appTitle: string;
  navBatch: string;
  navCheck: string;
  serviceLoading: string;
  serviceUnavailable: string;
  osmAttribution: string;

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
  pipelineSteps: string;
  unparsed: string;

  // Session view
  searchPlaceholder: string;
  inList: string;
  newFile: string;
  parsingInProgress: string;
  sessionNotFound: string;
  backToUpload: string;

  // Summary
  statRecords: string;
  statProcessed: string;
  statUncertain: string;
  statConfident: string;
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

  // Sources & tags
  sourceManual: string;
  sourceRef: string;
  sourceManualTooltip: string;
  sourceRefTooltip: string;
  sourceRefBase: string;
  msUnit: string;

  // UI v2: фильтры, редактор, загрузка, подсказки
  clear: string;
  uploadTitle: string;
  uploadSubtitle: string;
  dropRelease: string;
  formatExample: string;
  statusProcessing: string;
  statusDone: string;
  deleteBatch: string;
  deleteConfirm: string;
  batchDeleted: string;
  filterAria: string;
  filterAll: string;
  filterUncertain: string;
  filterEdited: string;
  resetFilters: string;
  thresholdMark: string;
  groupLocality: string;
  groupStreet: string;
  groupFlat: string;
  groupLandmark: string;
  revert: string;
  revertTo: string;
  setNull: string;
  changedCount: string;
  unsavedTitle: string;
  unsavedSave: string;
  unsavedDiscard: string;
  saved: string;
  saveError: string;
  pickHint: string;
  shortcutsTitle: string;
  kbNav: string;
  kbNavEditor: string;
  kbSave: string;
  kbClose: string;
  kbUncertain: string;
  kbSearch: string;
  kbHelp: string;
  kbPickHint: string;
  checkTitle: string;
  checkSubtitle: string;
  examples: string;
  liveHint: string;
  copyJson: string;
  copied: string;
  copyFailed: string;
  addedColumn: string;
  addedHint: string;
  sortHint: string;

  // ошибки, доступность, пагинация
  errorConnection: string;
  retry: string;
  sessionLoadError: string;
  sessionFailed: string;
  leaveConfirm: string;
  rowReviewed: string;
  rowNeedsReview: string;
  recordsTableAria: string;
  errorTitle: string;
  errorHint: string;
  errorReload: string;
  fileTooLarge: string;
  uploadProcessing: string;
  langAria: string;
  err413: string;
  err422: string;
  err409: string;
  err404: string;
  errServer: string;
  positionUnknown: string;

  // интерактивная гистограмма уверенности
  histHint: string;
  histRecords: string;
  histShare: string;
  histBelow: string;
  histClickShow: string;
  histClickReset: string;
  histBarAria: string;
  bucketChip: string;
  bucketClear: string;

  // окно экспорта
  exportTitle: string;
  exportScope: string;
  exportAll: string;
  exportCurrent: string;
  exportCurrentNone: string;
  exportSearch: string;
  exportFields: string;
  exportFieldsAlways: string;
  exportSelectAll: string;
  exportSelectNone: string;
  exportFormat: string;
  exportJsonHint: string;
  exportCsvHint: string;
  exportSources: string;
  exportSummary: string;
  exportDownload: string;
  exportOpen: string;

  // подтверждение, откладывание, отмена
  filterSkipped: string;
  filterReviewed: string;
  defer: string;
  deferHint: string;
  skippedBadge: string;
  unconfirm: string;
  unconfirmAria: string;
  returnToQueue: string;
  returnAria: string;
  toastConfirmed: string;
  toastDeferred: string;
  toastUnconfirmed: string;
  toastReturned: string;
  undo: string;
  undone: string;
  reviewProgress: string;
  skippedCount: string;
  rowSkipped: string;
  kbDefer: string;

  // шаги пайплайна
  traceSummary: string;
  howParsed: string;
  traceQuietShort: string;
  traceShowQuiet: string;
  traceHideQuiet: string;
  traceDetails: string;
  traceTokens: string;
  traceRemoved: string;
  traceKept: string;
  traceDropped: string;
  traceNotAddress: string;
  traceAgree: string;
  traceDispute: string;
  traceRulesOnly: string;
  traceModelOnly: string;
  traceWinnerRules: string;
  traceWinnerModel: string;
  traceOrientation: string;
  traceFinal: string;
  traceDup: string;
  traceNoise: string;

  // Field labels
  fields: Record<FieldName, string>;

  // Pipeline step names
  steps: Record<string, string>;
  // что делает шаг, одной фразой
  stepHints: Record<string, string>;
}

export type TranslationKey = keyof Omit<TranslationDictionary, "fields" | "steps" | "stepHints">;

export interface AvailableLanguage {
  code: Language;
  label: string;
  short: string;
  locale: string;
}
