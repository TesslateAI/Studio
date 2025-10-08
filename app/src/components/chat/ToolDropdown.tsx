import { useState, useRef, useEffect, type ReactNode } from 'react';

interface ToolItem {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  category?: 'actions' | 'tools';
}

interface ToolDropdownProps {
  icon: ReactNode;
  tools: ToolItem[];
}

export function ToolDropdown({ icon, tools }: ToolDropdownProps) {
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

  const handleToolClick = (tool: ToolItem) => {
    tool.onClick();
    setIsOpen(false);
  };

  // Group tools by category
  const actions = tools.filter(t => t.category === 'actions');
  const toolItems = tools.filter(t => t.category === 'tools');

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen(!isOpen);
        }}
        className="
          input-icon-btn
          w-9 h-9 rounded-xl
          bg-white/5 border border-white/10
          text-gray-400
          flex items-center justify-center
          transition-all
          hover:bg-white/10 hover:text-white
        "
      >
        {icon}
      </button>

      {isOpen && (
        <div className="
          icon-dropdown absolute bottom-full left-0 mb-2
          bg-[rgba(20,20,20,0.98)] backdrop-blur-xl
          border border-white/10 rounded-xl
          min-w-[200px] z-[1000]
          shadow-lg overflow-hidden
        ">
          {actions.length > 0 && (
            <>
              <div className="px-3 pt-2 pb-1 text-xs text-gray-400">
                ACTIONS
              </div>
              {actions.map((tool, idx) => (
                <button
                  key={idx}
                  onClick={() => handleToolClick(tool)}
                  className="
                    w-full px-4 py-2.5 flex items-center gap-3
                    text-sm text-white transition-colors
                    hover:bg-white/8
                  "
                >
                  <span className="text-base">{tool.icon}</span>
                  <span>{tool.label}</span>
                </button>
              ))}
            </>
          )}

          {actions.length > 0 && toolItems.length > 0 && (
            <div className="border-t border-white/10 my-2" />
          )}

          {toolItems.length > 0 && (
            <>
              <div className="px-3 pb-1 text-xs text-gray-400">
                TOOLS
              </div>
              {toolItems.map((tool, idx) => (
                <button
                  key={idx}
                  onClick={() => handleToolClick(tool)}
                  className="
                    w-full px-4 py-2.5 flex items-center gap-3
                    text-sm text-white transition-colors
                    hover:bg-white/8
                  "
                >
                  <span className="text-base">{tool.icon}</span>
                  <span>{tool.label}</span>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
