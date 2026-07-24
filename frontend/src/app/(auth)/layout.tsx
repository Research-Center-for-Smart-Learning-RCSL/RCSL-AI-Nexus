/**
 * Layout for screens that must render before anyone is authenticated.
 *
 * Deliberately outside `(dashboard)`: that layout fetches `/admin/me` and
 * assumes a session exists, which is exactly what is missing here. Nesting
 * these routes under it would produce a redirect loop on the login screen.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="nexus-dot-grid flex min-h-screen items-center justify-center bg-muted/40 p-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight">RCSL AI Nexus</h1>
          <p className="text-sm text-muted-foreground">Management</p>
        </div>
        {children}
      </div>
    </div>
  );
}
