import { AlertTriangle } from "lucide-react"

export function ErrorAlert({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex animate-fade-up items-start gap-2.5 rounded-lg border border-destructive/40 bg-destructive/10 px-3.5 py-3 text-sm text-destructive-foreground"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <span className="min-w-0 break-words">{message}</span>
    </div>
  )
}
