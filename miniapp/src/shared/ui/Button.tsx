import { type AnchorHTMLAttributes, type ButtonHTMLAttributes, forwardRef, type ReactNode, useId } from "react";

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

type Common = {
  variant?: ButtonVariant;
  /** Во всю ширину колонки — для основного действия на телефоне. */
  stretched?: boolean;
  small?: boolean;
};

function classes({ variant = "secondary", stretched, small }: Common, extra?: string) {
  return ["ds-btn", `ds-btn-${variant}`, stretched && "ds-btn-stretched", small && "ds-btn-small", extra]
    .filter(Boolean)
    .join(" ");
}

type ButtonProps = Common &
  ButtonHTMLAttributes<HTMLButtonElement> & {
    /** Идёт действие: кнопка показывает `loadingLabel` и не принимает повторный клик. */
    loading?: boolean;
    loadingLabel?: string;
    /**
     * Почему действие недоступно. Кнопка выключена, причина видна рядом и
     * связана с кнопкой через aria-describedby.
     */
    reason?: string | null;
  };

/** Кнопка — действие. Одна реализация на мини-приложение и кабинеты. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, stretched, small, loading = false, loadingLabel, reason, disabled, className, children, onClick, type = "button", ...rest },
  ref,
) {
  const reasonId = useId();
  const blocked = Boolean(disabled) || loading;
  const button = (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={classes({ variant, stretched, small }, className)}
      disabled={blocked}
      aria-busy={loading || undefined}
      aria-describedby={reason ? reasonId : rest["aria-describedby"]}
      onClick={(event) => {
        if (blocked) return;
        onClick?.(event);
      }}
    >
      {loading && loadingLabel ? loadingLabel : children}
    </button>
  );
  if (!reason) return button;
  return (
    <div className={stretched ? "ds-action ds-action-stretched" : "ds-action"}>
      {button}
      <p id={reasonId} className="ds-reason">
        {reason}
      </p>
    </div>
  );
});

type LinkProps = Common & AnchorHTMLAttributes<HTMLAnchorElement> & { children: ReactNode };

/** Ссылка, похожая на кнопку: она ведёт, а не действует. */
export function LinkButton({ variant, stretched, small, className, children, ...rest }: LinkProps) {
  return (
    <a className={classes({ variant, stretched, small }, className)} {...rest}>
      {children}
    </a>
  );
}
