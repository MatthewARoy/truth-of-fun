"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/explore");
  }, [router]);

  return (
    <section className="py-10 text-sm text-slate-300">Redirecting...</section>
  );
}
