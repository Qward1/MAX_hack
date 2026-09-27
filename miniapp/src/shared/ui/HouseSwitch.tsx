import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Sheet } from "./ChoicePicker";
import { IconCheck } from "./icons";

export type HouseOption = { id: string; address: string };

/**
 * Выбор дома в шапке экрана: кнопка с текущим адресом открывает список —
 * на широком экране под кнопкой, на телефоне листом снизу. Стрелки, Home и
 * End двигают курсор по списку, Enter и пробел выбирают, Esc закрывает без
 * смены; фокус возвращается на кнопку. Дом меняется только выбором, а не
 * каждым нажатием стрелки: смена дома перезагружает экран.
 */
export function HouseSwitch({
  houses,
  value,
  onChange,
}: {
  houses: HouseOption[];
  value: string;
  onChange: (houseId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const labelId = useId();
  const valueId = useId();
  const current = houses.find((house) => house.id === value) ?? houses[0];
  return (
    <span className="ds-house-switch">
      <span id={labelId}>Дом</span>
      <button
        ref={trigger}
        type="button"
        className="ds-picker-trigger ds-house-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-labelledby={`${labelId} ${valueId}`}
        title={current?.address}
        onClick={() => setOpen(true)}
      >
        <span id={valueId} className="ds-house-value">
          {current?.address}
        </span>
        <span className="ds-picker-caret" aria-hidden="true" />
      </button>
      {/* Лист — вне абзаца шапки: <dialog> не может быть внутри <p>. */}
      {open &&
        createPortal(
          <HouseList
            houses={houses}
            value={current?.id ?? ""}
            anchor={trigger.current}
            onPick={onChange}
            onClose={() => setOpen(false)}
          />,
          document.body,
        )}
    </span>
  );
}

function HouseList({
  houses,
  value,
  anchor,
  onPick,
  onClose,
}: {
  houses: HouseOption[];
  value: string;
  anchor: HTMLElement | null;
  onPick: (houseId: string) => void;
  onClose: () => void;
}) {
  const optionId = useId();
  const list = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(() => Math.max(0, houses.findIndex((house) => house.id === value)));
  // Рамка курсора — только при работе с клавиатуры; мышь и касание её не показывают.
  const [keyboard, setKeyboard] = useState(false);
  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [active]);
  function pick(index: number) {
    const house = houses[index];
    onClose();
    if (house && house.id !== value) onPick(house.id);
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const last = houses.length - 1;
    const moves: Record<string, number> = {
      ArrowDown: Math.min(active + 1, last),
      ArrowUp: Math.max(active - 1, 0),
      Home: 0,
      End: last,
    };
    if (event.key in moves) {
      event.preventDefault();
      setKeyboard(true);
      setActive(moves[event.key]);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      pick(active);
    }
  }
  return (
    <Sheet
      title="Выберите дом"
      anchor={anchor}
      popover
      closeLabel="Закрыть"
      focus="[role=listbox]"
      className="ds-house-sheet"
      onClose={onClose}
    >
      <div
        ref={list}
        role="listbox"
        tabIndex={0}
        aria-label="Дом"
        aria-activedescendant={`${optionId}-${active}`}
        className={["ds-house-options", keyboard && "is-keyboard"].filter(Boolean).join(" ")}
        onKeyDown={onKeyDown}
        onPointerMove={() => setKeyboard(false)}
      >
        {houses.map((house, index) => (
          <div
            key={house.id}
            id={`${optionId}-${index}`}
            data-index={index}
            role="option"
            aria-selected={house.id === value}
            className={["ds-house-option", index === active && "is-active"].filter(Boolean).join(" ")}
            onPointerEnter={() => setActive(index)}
            onClick={() => pick(index)}
          >
            <span className="ds-house-option-text">{house.address}</span>
            {house.id === value && <IconCheck />}
          </div>
        ))}
      </div>
    </Sheet>
  );
}
