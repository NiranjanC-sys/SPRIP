import { cn } from '@/lib/utils';

/**
 * Visually hidden but present in the accessibility tree. Use for the text half
 * of an icon-only control, and for table captions that would be redundant
 * on screen but are the only context a screen-reader user gets.
 */
export function VisuallyHidden({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn('sr-only', className)} {...props} />;
}
