import { type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";

export type Choice = { value: string; label: string; hint?: string };

/**
 * Лист поверх экрана на `<dialog>`: на телефоне — снизу (bottom sheet), с
 * `popover` на широком экране — рядом с кнопкой, которая его открыла.
 * Esc, нажатие на затемнение и кнопка закрытия закрывают его; фокус
 * возвращается на кнопку-источник.
 */
export function Sheet({
  title,
  anchor,
  popover = false,
  className,
  focus = "input:checked, [data-sheet-focus]",
  onClose,
  children,
}: {
  title: string;
  anchor?: HTMLElement | null;
  popover?: boolean;
  className?: string;
  /** Что получает фокус при открытии. */
  focus?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [anchored, setAnchored] = useState(false);
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const wide = typeof window.matchMedia === "function" && window.matchMedia("(min-width: 768px)").matches;
    if (popover && wide && anchor) {
      const box = anchor.getBoundingClientRect();
      const width = Math.max(box.width, 280);
      const left = Math.min(box.left, window.innerWidth - width - 16);
      dialog.style.setProperty("--sheet-top", `${Math.round(box.bottom + 6)}px`);
      dialog.style.setProperty("--sheet-left", `${Math.round(Math.max(16, left))}px`);
      dialog.style.setProperty("--sheet-width", `${Math.round(width)}px`);
      setAnchored(true);
    }
    if (!dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    dialog.querySelector<HTMLElement>(focus)?.focus();
  }, [anchor, popover, focus]);
  useEffect(() => {
    const dialog = ref.current;
    return () => {
      if (dialog?.open) dialog.close?.();
      anchor?.focus?.();
    };
  }, [anchor]);
  return (
    <dialog
      ref={ref}
      className={["ds-sheet", anchored && "is-popover", className].filter(Boolean).join(" ")}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        // Нажатие на затемнение вокруг листа закрывает его.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="ds-sheet-body">
        <p className="ds-sheet-title" id={titleId}>
          {title}
        </p>
        {children}
      </div>
    </dialog>
  );
}

/**
 * Выбор одного варианта в листе. Внутри — обычная группа переключателей:
 * стрелки меняют выбор, Esc и «Готово» закрывают, фокус возвращается на
 * кнопку. Выбор касанием или мышью сразу закрывает лист.
 */
export function ChoiceSheet({
  title,
  choices,
  value,
  anchor,
  onChange,
  onClose,
}: {
  title: string;
  choices: Choice[];
  value: string;
  anchor?: HTMLElement | null;
  onChange: (value: string) => void;
  onClose: () => void;
}) {
  const name = useId();
  const viaPointer = useRef(false);
  return (
    <Sheet title={title} anchor={anchor} popover onClose={onClose}>
      <fieldset
        className="ds-choice-list"
        onPointerDown={() => {
          viaPointer.current = true;
        }}
        onKeyDown={(event) => {
          viaPointer.current = false;
          if (event.key === "Enter") {
            event.preventDefault();
            onClose();
          }
        }}
      >
        <legend className="ds-visually-hidden">{title}</legend>
        {choices.map((choice) => (
          <label
            key={choice.value}
            className="ds-choice-row"
            onClick={(event) => {
              // Касание уже выбранного варианта тоже закрывает лист.
              if (event.detail > 0 && choice.value === value) onClose();
            }}
          >
            <input
              type="radio"
              name={name}
              value={choice.value}
              checked={choice.value === value}
              onChange={() => {
                onChange(choice.value);
                // Касание или мышь — выбор сделан; стрелки и пробел лист не закрывают.
                if (viaPointer.current) onClose();
              }}
            />
            <span className="ds-choice-text">
              <span>{choice.label}</span>
              {choice.hint && <span className="ds-hint">{choice.hint}</span>}
            </span>
          </label>
        ))}
      </fieldset>
      <button type="button" className="ds-btn ds-btn-secondary ds-btn-stretched ds-sheet-done" onClick={onClose}>
        Готово
      </button>
    </Sheet>
  );
}

/**
 * Поле выбора из короткого списка, где полезно видеть текущий выбор сразу:
 * кнопка с подписью и значением открывает `ChoiceSheet`. После выбора новое
 * значение видно на кнопке и сообщается экранному диктору.
 */
export function ChoicePicker({
  label,
  hint,
  value,
  choices,
  onChange,
  disabled = false,
}: {
  label: string;
  hint?: string;
  value: string;
  choices: Choice[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [announce, setAnnounce] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const labelId = useId();
  const valueId = useId();
  const hintId = useId();
  const current = choices.find((choice) => choice.value === value) ?? choices[0];
  return (
    <div className="ds-picker">
      <span className="ds-picker-label" id={labelId}>
        {label}
      </span>
      {hint && (
        <span className="ds-hint" id={hintId}>
          {hint}
        </span>
      )}
      <button
        ref={trigger}
        type="button"
        className="ds-picker-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-labelledby={`${labelId} ${valueId}`}
        aria-describedby={hint ? hintId : undefined}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <span id={valueId}>{current?.label}</span>
        <span className="ds-picker-caret" aria-hidden="true" />
      </button>
      <span className="ds-visually-hidden" role="status">
        {announce}
      </span>
      {open && (
        <ChoiceSheet
          title={label}
          choices={choices}
          value={value}
          anchor={trigger.current}
          onChange={(next) => {
            onChange(next);
            const chosen = choices.find((choice) => choice.value === next);
            if (chosen) setAnnounce(`${label}: ${chosen.label}`);
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
