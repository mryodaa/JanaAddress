import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AUTH_EVENT, ApiError, api } from "../api/client";
import { useI18n } from "../i18n";
import { errorText } from "../lib/errors";
import { IconAlert } from "./icons";
import { Button, Modal } from "./ui";

/**
 * Вход по ключу, если на сервисе задан JANA_API_KEY: любой ответ 401 открывает форму. Ключ уходит один раз,
 * дальше браузер шлёт cookie (HttpOnly), в JS и localStorage ключа нет.
 */
export function AuthGate() {
  const { t, language } = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const on = () => setOpen(true);
    window.addEventListener(AUTH_EVENT, on);
    return () => window.removeEventListener(AUTH_EVENT, on);
  }, []);

  async function submit() {
    if (!key.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.login(key);
      setOpen(false);
      setKey("");
      // всё, что упало на 401, перезапрашиваем уже с cookie
      await qc.invalidateQueries();
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? t("authWrong") : errorText(e, t, language));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={() => setOpen(false)} title={t("authTitle")}>
      <form
        className="grid gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p className="text-sm leading-relaxed text-ink-2">{t("authHint")}</p>
        <label className="grid gap-1.5 text-xs text-ink-2">
          {t("authKeyLabel")}
          <input
            type="password"
            autoComplete="current-password"
            // biome-ignore lint/a11y/noAutofocus: форма открывается ради одного поля
            autoFocus
            value={key}
            onChange={(e) => setKey(e.target.value)}
            className="h-10 rounded-xl border border-line bg-white px-3 font-mono text-sm text-ink outline-none transition focus:border-brand-600 focus:ring-4 focus:ring-brand-600/15"
          />
        </label>
        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger"
          >
            <IconAlert className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}
        <Button variant="primary" type="submit" loading={busy} disabled={!key.trim()}>
          {t("authSubmit")}
        </Button>
      </form>
    </Modal>
  );
}
