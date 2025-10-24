import { type ReactNode } from 'react';

interface SidebarItem {
  icon: ReactNode;
  title: string;
  onClick: () => void;
  active?: boolean;
  dataTour?: string;
}

interface FloatingSidebarProps {
  position: 'left' | 'right';
  items: SidebarItem[];
}

export function FloatingSidebar({ position, items }: FloatingSidebarProps) {
  return (
    <div
      className={`
        hidden md:flex
        fixed ${position === 'left' ? 'left-4 md:left-6' : 'right-4 md:right-6'}
        top-1/2 -translate-y-1/2
        flex-col gap-3
        z-40
      `}
    >
      {items.map((item, index) => (
        <button
          key={index}
          onClick={item.onClick}
          title={item.title}
          data-tour={item.dataTour}
          className={`
            sidebar-icon
            w-12 h-12
            flex items-center justify-center
            rounded-xl
            bg-white/[0.03]
            border border-white/[0.08]
            transition-all duration-300 ease-[var(--ease)]
            ${item.active
              ? 'bg-gradient-to-br from-[rgba(255,107,0,0.3)] to-[rgba(255,107,0,0.2)] text-[var(--primary)] border-[rgba(255,107,0,0.4)] shadow-[0_0_20px_rgba(255,107,0,0.2)]'
              : 'text-gray-500 hover:bg-[rgba(255,107,0,0.15)] hover:text-[var(--primary)] hover:border-[rgba(255,107,0,0.3)] hover:scale-110'
            }
          `}
        >
          {item.icon}
        </button>
      ))}
    </div>
  );
}
