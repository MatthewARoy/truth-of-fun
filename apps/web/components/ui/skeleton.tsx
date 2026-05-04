import { cn } from "@/lib/cn";

type Props = {
  className?: string;
};

export function Skeleton({ className }: Props) {
  return <div className={cn("animate-pulse rounded-ui bg-slate-800/80", className)} aria-hidden="true" />;
}
