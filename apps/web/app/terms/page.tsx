import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage, LegalSection } from "@/components/legal-page";
import { pageMetadata } from "@/lib/metadata";
import { SITE_NAME } from "@/lib/site";

export const metadata: Metadata = pageMetadata({
  title: "Terms",
  description: `Draft terms of use for ${SITE_NAME}. Pending legal review.`,
  path: "/terms",
});

const LIST = "list-disc space-y-1 pl-5";

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Use (draft)">
      <p>
        These terms cover your use of {SITE_NAME}, operated by [Company legal name]. Last updated:
        [date]. By using the service you agree to them. [Confirm acceptance mechanism.]
      </p>

      <LegalSection heading="What the service is">
        <p>
          {SITE_NAME} is an event discovery service for the San Francisco Bay Area. It collects event
          listings from third-party sources, lets you search and filter them, suggests events based on
          your interests, and helps you put together and share a plan.
        </p>
      </LegalSection>

      <LegalSection heading="Event information comes from other people">
        <ul className={LIST}>
          <li>
            Listings are gathered automatically from third-party sources and link back to them. We do
            not organize, host or sell tickets to the events.
          </li>
          <li>
            Details can be wrong or out of date. Events get cancelled, postponed, moved or sold out,
            and prices change. Some listings have no published start time or price; where that is the
            case the site says so rather than guessing.
          </li>
          <li>
            Always confirm the date, time, place, price and any age or entry requirements with the
            organizer or ticket seller before you travel or pay.
          </li>
          <li>
            Travel times and &ldquo;leave by&rdquo; suggestions in plans are estimates and do not
            account for live traffic or transit conditions.
          </li>
          <li>Tickets and purchases are between you and the seller, under the seller&apos;s terms.</li>
        </ul>
      </LegalSection>

      <LegalSection heading="Your account">
        <ul className={LIST}>
          <li>Keep your password private and use an email address you control.</li>
          <li>You are responsible for activity under your account and for access tokens you create.</li>
          <li>
            You can delete your account at any time from the <Link href="/account">Account</Link>{" "}
            page.
          </li>
          <li>[Minimum age requirement.]</li>
        </ul>
      </LegalSection>

      <LegalSection heading="Things you share">
        <p>
          Shared plan links and shared folder links can be opened by anyone who has them. Only put
          information in a shared plan or a folder name that you are comfortable making public, and do
          not include other people&apos;s private information. See the{" "}
          <Link href="/privacy">Privacy Policy</Link> for what a shared link contains.
        </p>
      </LegalSection>

      <LegalSection heading="Acceptable use">
        <ul className={LIST}>
          <li>Do not try to break, overload or gain unauthorized access to the service.</li>
          <li>Do not use it to harass people or to publish unlawful content through shared links.</li>
          <li>[Rules for automated access, scraping and API or agent-token use.]</li>
        </ul>
      </LegalSection>

      <LegalSection heading="Still to be completed">
        <ul className={LIST}>
          <li>[Disclaimer of warranties.]</li>
          <li>[Limitation of liability.]</li>
          <li>[Intellectual property and takedown contact for event organizers and rights holders.]</li>
          <li>[Suspension and termination.]</li>
          <li>[Governing law and dispute resolution.]</li>
          <li>[How changes to these terms are announced.]</li>
        </ul>
      </LegalSection>

      <LegalSection heading="Contact">
        <p>[Company legal name], [postal address], [contact email].</p>
      </LegalSection>
    </LegalPage>
  );
}
