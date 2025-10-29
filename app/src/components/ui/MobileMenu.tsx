import { type ReactNode, useState } from 'react';
import { List, X } from '@phosphor-icons/react';

interface MenuItem {
  icon: ReactNode;
  title: string;
  onClick: () => void;
  active?: boolean;
  section?: 'left' | 'right';
}

interface MobileMenuProps {
  leftItems: Array<{
    icon: ReactNode;
    title: string;
    onClick: () => void;
    active?: boolean;
    dataTour?: string;
  }>;
  rightItems: Array<{
    icon: ReactNode;
    title: string;
    onClick: () => void;
    active?: boolean;
    dataTour?: string;
  }>;
}

export function MobileMenu({ leftItems, rightItems }: MobileMenuProps) {
  const [isOpen, setIsOpen] = useState(false);

  const handleItemClick = (onClick: () => void) => {
    onClick();
    setIsOpen(false);
  };

  return (
    <>
      {/* Hamburger Button - Mobile only */}
      <button
        onClick={() => setIsOpen(true)}
        className="md:hidden fixed top-4 right-4 z-50 w-12 h-12 bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 flex items-center justify-center text-[var(--text)] transition-all"
      >
        <List size={24} weight="bold" />
      </button>

      {/* Mobile Menu Overlay */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="md:hidden fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]"
            onClick={() => setIsOpen(false)}
          />

          {/* Menu Panel */}
          <div className="md:hidden fixed top-0 right-0 h-full w-80 max-w-[85vw] bg-[var(--surface)] border-l border-white/10 z-[70] shadow-2xl overflow-y-auto">
            {/* Header */}
            <div className="sticky top-0 bg-[var(--surface)] border-b border-white/10 p-4 flex items-center justify-between">
              <h2 className="font-heading text-lg font-bold text-[var(--text)]">Menu</h2>
              <button
                onClick={() => setIsOpen(false)}
                className="w-10 h-10 flex items-center justify-center rounded-lg hover:bg-white/10 transition-colors text-[var(--text)]"
              >
                <X size={24} weight="bold" />
              </button>
            </div>

            {/* Menu Items */}
            <div className="p-4 space-y-6">
              {/* Left Section Items */}
              {leftItems.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Navigation</h3>
                  <div className="space-y-2">
                    {leftItems.map((item, index) => (
                      <button
                        key={index}
                        onClick={() => handleItemClick(item.onClick)}
                        data-tour={item.dataTour}
                        className={`
                          w-full flex items-center gap-3 px-4 py-3 rounded-xl
                          transition-all duration-200
                          ${item.active
                            ? 'bg-gradient-to-r from-[rgba(255,107,0,0.2)] to-[rgba(255,107,0,0.1)] text-[var(--primary)] border border-[rgba(255,107,0,0.3)]'
                            : 'bg-white/5 text-[var(--text)] hover:bg-white/10 border border-transparent'
                          }
                        `}
                      >
                        <div className={`${item.active ? 'text-[var(--primary)]' : 'text-gray-500'}`}>
                          {item.icon}
                        </div>
                        <span className="font-medium">{item.title}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Right Section Items */}
              {rightItems.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Actions</h3>
                  <div className="space-y-2">
                    {rightItems.map((item, index) => (
                      <button
                        key={index}
                        onClick={() => handleItemClick(item.onClick)}
                        data-tour={item.dataTour}
                        className={`
                          w-full flex items-center gap-3 px-4 py-3 rounded-xl
                          transition-all duration-200
                          ${item.active
                            ? 'bg-gradient-to-r from-[rgba(255,107,0,0.2)] to-[rgba(255,107,0,0.1)] text-[var(--primary)] border border-[rgba(255,107,0,0.3)]'
                            : 'bg-white/5 text-[var(--text)] hover:bg-white/10 border border-transparent'
                          }
                        `}
                      >
                        <div className={`${item.active ? 'text-[var(--primary)]' : 'text-gray-500'}`}>
                          {item.icon}
                        </div>
                        <span className="font-medium">{item.title}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
