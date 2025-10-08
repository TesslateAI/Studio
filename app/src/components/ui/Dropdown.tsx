import { useState, useRef, useEffect, type ReactNode } from 'react';

interface DropdownItem {
  icon?: ReactNode;
  label: string;
  onClick: () => void;
  variant?: 'default' | 'danger';
  separator?: boolean;
}

interface DropdownProps {
  trigger: ReactNode;
  items: DropdownItem[];
  position?: 'bottom-left' | 'bottom-right';
}

export function Dropdown({ trigger, items, position = 'bottom-right' }: DropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleItemClick = (item: DropdownItem) => {
    item.onClick();
    setIsOpen(false);
  };

  return (
    <div className="relative inline-block" ref={dropdownRef}>
      <div
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen(!isOpen);
        }}
        className="cursor-pointer"
      >
        {trigger}
      </div>

      {isOpen && (
        <div
          className={`
            dropdown-menu absolute top-full mt-2
            ${position === 'bottom-right' ? 'right-0' : 'left-0'}
            bg-[rgba(20,20,20,0.98)] backdrop-blur-xl
            border border-white/10 rounded-xl
            min-w-[160px] z-50
            shadow-[0_8px_32px_rgba(0,0,0,0.3)]
            overflow-hidden
          `}
        >
          {items.map((item, index) => (
            <div key={index}>
              {item.separator && index > 0 && (
                <div className="border-t border-white/5 my-1" />
              )}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleItemClick(item);
                }}
                className={`
                  dropdown-item w-full px-4 py-2.5
                  flex items-center gap-3
                  text-sm transition-colors
                  hover:bg-white/8
                  ${item.variant === 'danger' ? 'text-red-400' : 'text-white'}
                `}
              >
                {item.icon && <span className="text-base">{item.icon}</span>}
                <span>{item.label}</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
