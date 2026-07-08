"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearSession, getStoredUser, getToken } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/patients", label: "Patients" },
  { href: "/review", label: "Review Queue" },
  { href: "/audit", label: "Audit Log" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<{ full_name: string; role: string } | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(getStoredUser());
  }, [router]);

  if (!user) return null;

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">HH RN Platform</div>
        {NAV.map((item) => (
          <Link key={item.href} href={item.href}
                className={pathname.startsWith(item.href) ? "active" : ""}>
            {item.label}
          </Link>
        ))}
        <div className="spacer" />
        <div className="whoami">
          {user.full_name}
          <br />
          <span style={{ opacity: 0.7 }}>{user.role.replaceAll("_", " ")}</span>
          <br />
          <a href="/login" onClick={() => clearSession()} style={{ padding: 0 }}>
            Sign out
          </a>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
