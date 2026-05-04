"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { FolderResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Input } from "@/components/ui/input";

export default function FoldersPage() {
  const [folders, setFolders] = useState<FolderResponse[]>([]);
  const [newName, setNewName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadFolders() {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.listFolders();
      setFolders(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadFolders();
  }, []);

  async function createFolder() {
    if (!newName.trim()) {
      return;
    }
    setError(null);
    try {
      await apiClient.createFolder(newName.trim());
      setNewName("");
      await loadFolders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Vibe Folders</h2>
      <Card className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <Input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            label="Create a new folder"
            placeholder="Saturday options"
          />
        </div>
        <Button type="button" onClick={() => void createFolder()} variant="secondary">
          Create
        </Button>
      </Card>
      {loading ? <InlineNotice>Loading folders...</InlineNotice> : null}
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
      {!loading && !error && folders.length === 0 ? <InlineNotice>No folders yet.</InlineNotice> : null}
      <ul className="space-y-2">
        {folders.map((folder) => (
          <li key={folder.id} className="rounded-ui border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-center justify-between">
              <p>{folder.name}</p>
              <Link href={`/folders/${folder.id}`} className="text-brand-200">
                Open
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
