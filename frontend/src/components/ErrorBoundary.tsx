import { Component, type ErrorInfo, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { IconAlert } from "./icons";
import { Button } from "./ui";

function Fallback({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div
      role="alert"
      className="mx-auto mt-10 flex max-w-md animate-fade-up flex-col items-center gap-3 rounded-[20px] border border-line bg-white p-8 text-center"
    >
      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-danger-50 text-danger">
        <IconAlert className="h-5 w-5" />
      </span>
      <div className="text-base font-semibold">{t("errorTitle")}</div>
      <div className="text-sm text-ink-2">{t("errorHint")}</div>
      <div className="flex gap-2">
        <Button variant="primary" onClick={onRetry}>
          {t("retry")}
        </Button>
        <Button onClick={() => window.location.reload()}>{t("errorReload")}</Button>
      </div>
    </div>
  );
}

/**
 * Ошибка отрисовки одной вкладки не должна оставлять белый экран всего приложения: показываем карточку
 * с повтором, остальные вкладки работают. resetKey (смена вкладки) сбрасывает ошибку.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; resetKey?: string },
  { failed: boolean; key?: string }
> {
  state: { failed: boolean; key?: string } = { failed: false, key: this.props.resetKey };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  static getDerivedStateFromProps(
    props: { resetKey?: string },
    state: { failed: boolean; key?: string },
  ): { failed: boolean; key?: string } | null {
    return props.resetKey !== state.key ? { failed: false, key: props.resetKey } : null;
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI error", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.failed) return <Fallback onRetry={() => this.setState({ failed: false })} />;
    return this.props.children;
  }
}
