import { motion } from 'framer-motion';
import { cardSpring } from './motion';

export interface StatCardProps {
  value: number | string;
  label: string;
  index?: number;
}

export function StatCard({ value, label, index = 0 }: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...cardSpring, delay: index * 0.05 }}
      className="relative bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-4 sm:p-5 overflow-hidden"
    >
      <div className="font-heading text-2xl font-bold tracking-tight text-[var(--text)]">
        {value}
      </div>
      <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mt-1">{label}</div>
    </motion.div>
  );
}
