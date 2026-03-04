import { CaretLeft, CaretRight } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ currentPage, totalPages, onPageChange }: PaginationProps) {
  const { theme } = useTheme();

  if (totalPages <= 1) return null;

  // Build page numbers with ellipsis
  const getPageNumbers = (): (number | 'ellipsis')[] => {
    const pages: (number | 'ellipsis')[] = [];

    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
      return pages;
    }

    // Always show first page
    pages.push(1);

    if (currentPage > 3) {
      pages.push('ellipsis');
    }

    // Pages around current
    const start = Math.max(2, currentPage - 1);
    const end = Math.min(totalPages - 1, currentPage + 1);
    for (let i = start; i <= end; i++) {
      pages.push(i);
    }

    if (currentPage < totalPages - 2) {
      pages.push('ellipsis');
    }

    // Always show last page
    pages.push(totalPages);

    return pages;
  };

  const pageNumbers = getPageNumbers();

  const baseBtn = `flex items-center justify-center rounded-lg text-sm font-medium transition-colors`;
  const inactiveBtn =
    theme === 'light'
      ? 'text-black/60 hover:bg-black/5 hover:text-black'
      : 'text-white/60 hover:bg-white/5 hover:text-white';
  const activeBtn =
    'bg-[var(--primary)] text-white';
  const disabledBtn =
    theme === 'light' ? 'text-black/20 cursor-not-allowed' : 'text-white/20 cursor-not-allowed';

  return (
    <nav className="flex items-center justify-center gap-1 mt-8" aria-label="Pagination">
      {/* Previous */}
      <button
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage <= 1}
        className={`${baseBtn} w-9 h-9 ${currentPage <= 1 ? disabledBtn : inactiveBtn}`}
        aria-label="Previous page"
      >
        <CaretLeft size={16} weight="bold" />
      </button>

      {/* Page numbers */}
      {pageNumbers.map((page, i) =>
        page === 'ellipsis' ? (
          <span
            key={`ellipsis-${i}`}
            className={`w-9 h-9 flex items-center justify-center text-sm ${theme === 'light' ? 'text-black/30' : 'text-white/30'}`}
          >
            ...
          </span>
        ) : (
          <button
            key={page}
            onClick={() => onPageChange(page)}
            className={`${baseBtn} w-9 h-9 ${page === currentPage ? activeBtn : inactiveBtn}`}
            aria-label={`Page ${page}`}
            aria-current={page === currentPage ? 'page' : undefined}
          >
            {page}
          </button>
        )
      )}

      {/* Next */}
      <button
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage >= totalPages}
        className={`${baseBtn} w-9 h-9 ${currentPage >= totalPages ? disabledBtn : inactiveBtn}`}
        aria-label="Next page"
      >
        <CaretRight size={16} weight="bold" />
      </button>
    </nav>
  );
}
