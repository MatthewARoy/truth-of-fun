"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiClientError } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { localDateKey } from "@/lib/localtime";
import { PASSWORD_MIN_LENGTH, passwordProblem } from "@/lib/password";
import { VIBE_OPTIONS } from "@/lib/vibes";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Input } from "@/components/ui/input";

export default function AccountPage() {
  const { ready, token, email } = useAuth();
  if (!ready) return <InlineNotice>Loading your account...</InlineNotice>;
  if (!token) {
    return (
      <section className="mx-auto max-w-2xl space-y-4">
        <h1 className="text-xl font-semibold">Account</h1>
        <InlineNotice tone="info">Sign in to manage your account.</InlineNotice>
        <Link href="/login?next=%2Faccount" className="text-brand-200 underline">Sign in</Link>
      </section>
    );
  }
  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">Account</h1>
        <p className="text-sm text-slate-400">
          Signed in as <span className="break-all text-slate-200">{email}</span>
        </p>
      </div>
      <Interests />
      <ChangePassword email={email} />
      <Sessions />
      <DataExport />
      <DeleteAccount />
    </section>
  );
}

function message(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

function Interests() {
  const [selected, setSelected] = useState<string[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    apiClient.getMyProfile({ signal: controller.signal })
      .then((profile) => {
        if (!controller.signal.aborted) setSelected(profile.preferred_vibes ?? []);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setLoadError(message(err, "Could not load your interests."));
      });
    return () => controller.abort();
  }, [attempt]);

  function toggle(tag: string) {
    setSaved(false);
    setSelected((current) => {
      const list = current ?? [];
      return list.includes(tag) ? list.filter((entry) => entry !== tag) : [...list, tag];
    });
  }

  async function save() {
    if (!selected) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const response = await apiClient.setPreferences({ preferred_vibes: selected });
      setSelected(response.preferred_vibes ?? selected);
      setSaved(true);
    } catch (err) {
      setError(message(err, "Could not save your interests."));
    } finally {
      setSaving(false);
    }
  }

  // Interests picked up elsewhere (onboarding text, liking a tag on an event)
  // may not be in the standard list; show them so saving never drops them
  // silently and they can still be removed.
  const known = new Set<string>(VIBE_OPTIONS.map((option) => option.tag));
  const extras = (selected ?? []).filter((tag) => !known.has(tag));

  return (
    <Card className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">Your interests</h2>
        <p className="text-sm text-slate-400">
          These shape your recommendations. Change them whenever you like.
        </p>
      </div>
      {loadError ? (
        <InlineNotice tone="error">
          {loadError}{" "}
          <Button
            type="button" variant="ghost" size="sm"
            onClick={() => { setLoadError(null); setAttempt((value) => value + 1); }}
          >
            Retry
          </Button>
        </InlineNotice>
      ) : selected === null ? (
        <InlineNotice>Loading your interests...</InlineNotice>
      ) : (
        <>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Interests">
            {VIBE_OPTIONS.map((option) => (
              <Chip key={option.tag} size="md" pressed={selected.includes(option.tag)} onClick={() => toggle(option.tag)}>
                <span aria-hidden="true">{option.emoji}</span> {option.label}
              </Chip>
            ))}
            {extras.map((tag) => (
              <Chip key={tag} size="md" pressed onClick={() => toggle(tag)}>{tag}</Chip>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" onClick={() => void save()} disabled={saving}>
              {saving ? "Saving..." : "Save interests"}
            </Button>
            {saved ? <span role="status" className="text-sm text-emerald-200">Interests saved.</span> : null}
          </div>
          {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        </>
      )}
    </Card>
  );
}

function ChangePassword({ email }: { email: string | null }) {
  const { setSession } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setDone(false);
    const problem = passwordProblem(next);
    if (problem) return setError(problem);
    if (next !== confirmation) return setError("The two new passwords do not match.");
    if (next === current) return setError("Choose a new password that is different from the current one.");
    setSaving(true);
    setError(null);
    try {
      const response = await apiClient.changePassword({ current_password: current, new_password: next });
      // The old token stopped working; adopt the new one so this tab stays signed in.
      setSession(response);
      setCurrent("");
      setNext("");
      setConfirmation("");
      setDone(true);
    } catch (err) {
      setError(message(err, "Could not change your password."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">Change password</h2>
        <p className="text-sm text-slate-400">
          Changing your password signs out every other device and browser.
        </p>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Lets password managers attach the new password to the right account. */}
        <input type="hidden" name="username" autoComplete="username" value={email ?? ""} readOnly />
        <Input
          label="Current password"
          type="password"
          name="current-password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          required
        />
        <Input
          label="New password"
          type="password"
          name="new-password"
          autoComplete="new-password"
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          value={next}
          onChange={(e) => setNext(e.target.value)}
          required
          minLength={PASSWORD_MIN_LENGTH}
        />
        <Input
          label="Confirm new password"
          type="password"
          name="confirm-new-password"
          autoComplete="new-password"
          value={confirmation}
          onChange={(e) => setConfirmation(e.target.value)}
          required
        />
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        {done ? (
          <InlineNotice tone="success">Password changed. Other devices have been signed out.</InlineNotice>
        ) : null}
        <Button type="submit" disabled={saving}>{saving ? "Saving..." : "Change password"}</Button>
      </form>
    </Card>
  );
}

function Sessions() {
  const router = useRouter();
  const { logout } = useAuth();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signOutEverywhere() {
    setWorking(true);
    setError(null);
    try {
      await apiClient.logoutEverywhere();
    } catch (err) {
      // A token the API already rejects is as signed-out as it gets.
      if (!(err instanceof ApiClientError && err.status === 401)) {
        setError(message(err, "Could not sign out your other devices. Please try again."));
        setWorking(false);
        return;
      }
    }
    logout();
    router.replace("/");
  }

  return (
    <Card className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">Sign out everywhere</h2>
        <p className="text-sm text-slate-400">
          Ends every session on every device, including this one. Use it if you signed in on a shared
          computer or think someone else has access.
        </p>
      </div>
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      <Button type="button" variant="secondary" onClick={() => void signOutEverywhere()} disabled={working}>
        {working ? "Signing out..." : "Sign out everywhere"}
      </Button>
    </Card>
  );
}

function DataExport() {
  const [working, setWorking] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setWorking(true);
    setError(null);
    setDone(false);
    try {
      const data = await apiClient.exportMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `truth-of-fun-data-${localDateKey()}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Give the browser a moment to start the download before releasing it.
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      setDone(true);
    } catch (err) {
      setError(message(err, "Could not prepare your data. Please try again."));
    } finally {
      setWorking(false);
    }
  }

  return (
    <Card className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">Download your data</h2>
        <p className="text-sm text-slate-400">
          Get a copy of the data stored about your account as a JSON file.
        </p>
      </div>
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      {done ? <InlineNotice tone="success">Your data file has been downloaded.</InlineNotice> : null}
      <Button type="button" variant="secondary" onClick={() => void download()} disabled={working}>
        {working ? "Preparing..." : "Download my data"}
      </Button>
    </Card>
  );
}

function DeleteAccount() {
  const router = useRouter();
  const { logout } = useAuth();
  const [password, setPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!confirmed || !password) return;
    setWorking(true);
    setError(null);
    try {
      await apiClient.deleteAccount({ password });
    } catch (err) {
      setError(message(err, "Could not delete your account."));
      setWorking(false);
      return;
    }
    logout();
    router.replace("/");
  }

  return (
    <Card className="space-y-4 border-rose-900">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-rose-100">Delete account</h2>
        <p className="text-sm text-slate-400">
          Permanently deletes your account and the data tied to it. This cannot be undone. Consider
          downloading your data first.
        </p>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Enter your password to confirm"
          type="password"
          name="delete-password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <label className="flex items-start gap-2 text-sm text-slate-200">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>I understand that my account and its data will be permanently deleted.</span>
        </label>
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
        <Button type="submit" variant="danger" disabled={working || !confirmed || !password}>
          {working ? "Deleting..." : "Delete my account"}
        </Button>
      </form>
    </Card>
  );
}
