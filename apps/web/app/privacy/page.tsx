import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage, LegalSection } from "@/components/legal-page";
import { pageMetadata } from "@/lib/metadata";
import { SITE_NAME } from "@/lib/site";

export const metadata: Metadata = pageMetadata({
  title: "Privacy",
  description: `Draft description of what ${SITE_NAME} does with your data. Pending legal review.`,
  path: "/privacy",
});

const LIST = "list-disc space-y-1 pl-5";

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy (draft)">
      <p>
        {SITE_NAME} is operated by [Company legal name] (&ldquo;we&rdquo;). This page describes what
        the service does with information about you. Last updated: [date].
      </p>

      <LegalSection heading="You can browse without an account">
        <p>
          Searching and viewing events, building a plan, and opening a shared plan or shared folder do
          not require an account.
        </p>
      </LegalSection>

      <LegalSection heading="What we store when you create an account">
        <ul className={LIST}>
          <li>Your email address.</li>
          <li>
            Your password, stored only as a salted hash. We cannot see your password and it is never
            included in a data export.
          </li>
          <li>
            Your interests: the categories you pick at sign-up or on your account page, and any
            derived from the description you enter during onboarding.
          </li>
          <li>Events you save, and folders (shortlists) you create, including votes on their items.</li>
          <li>
            Activity used to personalize recommendations while you are signed in: events you save,
            tags you like, event pages you open, and ticket links you follow.
          </li>
          <li>
            Plans you choose to publish as a shared link, and any access tokens you create for apps or
            agents.
          </li>
        </ul>
        <p>
          We use this information to run your account, show your saved items, and rank
          recommendations for you.
        </p>
      </LegalSection>

      <LegalSection heading="Things that are public to anyone with the link">
        <ul className={LIST}>
          <li>
            <strong>Shared plans.</strong> When you create a public link for an itinerary, anyone who
            has the link can read the plan: its title, its stops, any stops you added yourself and, if
            you chose to include it, your starting point. The request you typed to build the plan is
            not included. Links expire after the period you choose (up to 30 days) and you can revoke
            them earlier on the <Link href="/shared-plans">Shared plans</Link> page.
          </li>
          <li>
            <strong>Shared folders.</strong> A folder&apos;s share link shows the folder name and the
            events in it, with their vote totals, to anyone who has the link. An invite link lets a
            signed-in person join the folder and vote.
          </li>
        </ul>
        <p>
          Shared pages are marked so that search engines do not index them, but treat any link you
          share as public: whoever receives it can pass it on.
        </p>
      </LegalSection>

      <LegalSection heading="Location">
        <p>
          The &ldquo;Near me&rdquo; filter asks your browser for your location only when you turn it
          on. Your approximate position is sent with that search so results can be sorted by distance.
          The website does not save it to your account or put it in the page address. If you give the
          planner a starting point, it is used to build that plan and appears in a shared link only if
          you choose to include it.
        </p>
        <p>[Confirm how long server request logs, which can contain search parameters, are kept.]</p>
      </LegalSection>

      <LegalSection heading="Stored in your browser">
        <p>
          When you sign in, the website keeps your sign-in token and email address in your
          browser&apos;s local storage so you stay signed in. Signing out removes them. The website
          does not load advertising or third-party analytics scripts. [Confirm before publishing, and
          update if analytics are added.]
        </p>
      </LegalSection>

      <LegalSection heading="Where event information comes from, and third parties your browser contacts">
        <ul className={LIST}>
          <li>
            Event listings are gathered from third-party sources such as ticketing services, public
            calendars and community listings. Each event links back to its source, and following a
            ticket or event link takes you to a site we do not control.
          </li>
          <li>
            Event images are loaded directly from the sites that host them. Your browser contacts
            those sites to fetch the image (we ask it not to send a referring page address).
          </li>
          <li>
            The map view loads map tiles from CARTO, based on OpenStreetMap data. Directions links
            open Google Maps.
          </li>
          <li>[List service providers that process data on our behalf: hosting, email delivery, any AI or geocoding providers used to build plans.]</li>
        </ul>
      </LegalSection>

      <LegalSection heading="Your choices">
        <ul className={LIST}>
          <li>
            <strong>Download your data.</strong> Signed-in users can download a JSON copy of their
            account data from the <Link href="/account">Account</Link> page.
          </li>
          <li>
            <strong>Delete your account.</strong> You can permanently delete your account from the{" "}
            <Link href="/account">Account</Link> page by confirming your password.
            [Describe exactly what is deleted and any retention of backups or logs.]
          </li>
          <li>
            <strong>Change interests or password, or sign out everywhere</strong> on the same page.
          </li>
        </ul>
      </LegalSection>

      <LegalSection heading="Still to be completed">
        <ul className={LIST}>
          <li>[Legal bases for processing and applicable law, e.g. CCPA/CPRA rights.]</li>
          <li>[Data retention periods.]</li>
          <li>[Children&apos;s privacy and minimum age.]</li>
          <li>[International transfers, if any.]</li>
          <li>[How changes to this policy are announced.]</li>
        </ul>
      </LegalSection>

      <LegalSection heading="Contact">
        <p>Questions or requests about your data: [contact email]. [Company legal name], [postal address].</p>
      </LegalSection>
    </LegalPage>
  );
}
