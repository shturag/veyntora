import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import { BrandMark } from "@/components/brand";

export async function generateMetadata(): Promise<Metadata> {
  return { title: { absolute: (await getTranslations("common"))("brand") } };
}

const btn = "inline-flex h-11 items-center gap-2 rounded-[10px] px-5 text-sm font-semibold no-underline box-border";
const btnLight = `${btn} bg-white !text-hero hover:bg-[#E6E8F8]`;
const btnOutline = `${btn} border border-hero-line !text-white hover:border-hero-accent`;
const card =
  "relative flex flex-col gap-3 overflow-hidden rounded-[18px] border border-line bg-surface p-[26px] !text-fg no-underline transition hover:-translate-y-1 hover:border-accent-soft-strong hover:shadow-[0_18px_40px_rgba(18,19,24,0.1)]";

function Icon({ bg, stroke, children }: { bg: string; stroke: string; children: ReactNode }) {
  return (
    <div className="flex size-11 items-center justify-center rounded-xl" style={{ background: bg }}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        {children}
      </svg>
    </div>
  );
}

function FeatureCard({
  href,
  title,
  body,
  more,
  icon,
  className = "",
  children,
}: {
  href: string;
  title: string;
  body: string;
  more: string;
  icon: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <Link href={href} className={`${card} group ${className}`}>
      {icon}
      <h3 className="m-0 text-[19px] tracking-[-0.01em]">{title}</h3>
      <p className="m-0 text-[14.5px] leading-normal text-fg-muted">{body}</p>
      {children}
      <span className="mt-auto text-sm font-semibold text-accent group-hover:underline">{more}</span>
    </Link>
  );
}

function RequestFlow({ t }: { t: (key: string) => string }) {
  return (
    <svg viewBox="0 0 1200 380" width="100%" role="img" aria-label={t("flowAria")}>
      <defs>
        <linearGradient id="gf" x1="0" x2="1">
          <stop offset="0" stopColor="#8B98F5" />
          <stop offset="1" stopColor="#5DD39E" />
        </linearGradient>
        <filter id="gl">
          <feGaussianBlur stdDeviation="3" />
        </filter>
      </defs>
      <g fill="none" strokeWidth="2">
        <path d="M170 190 H240" stroke="#3A3D4D" />
        <path id="pf" d="M170 190 H390 C435 190 435 80 480 80 H960 C1005 80 975 190 1010 190" stroke="#3A3D4D" />
        <path id="pa" d="M170 190 H390 C435 190 435 300 480 300 H960 C1005 300 975 190 1010 190" stroke="#3A3D4D" />
        <path d="M390 190 C435 190 435 80 480 80 H960 C1005 80 975 190 1010 190" stroke="url(#gf)" strokeOpacity=".55" className="vey-march" />
        <path d="M390 190 C435 190 435 300 480 300 H960 C1005 300 975 190 1010 190" stroke="#E0A458" strokeOpacity=".45" className="vey-march" />
      </g>
      <g>
        <circle r="6" fill="#8B98F5" filter="url(#gl)">
          <animateMotion dur="3.2s" repeatCount="indefinite">
            <mpath href="#pf" />
          </animateMotion>
        </circle>
        <circle r="4" fill="#fff">
          <animateMotion dur="3.2s" repeatCount="indefinite">
            <mpath href="#pf" />
          </animateMotion>
        </circle>
        <circle r="4" fill="#fff">
          <animateMotion dur="3.2s" begin="1.6s" repeatCount="indefinite">
            <mpath href="#pf" />
          </animateMotion>
        </circle>
        <circle r="6" fill="#E0A458" filter="url(#gl)">
          <animateMotion dur="6s" begin=".8s" repeatCount="indefinite">
            <mpath href="#pa" />
          </animateMotion>
        </circle>
        <circle r="4" fill="#FCE3BF">
          <animateMotion dur="6s" begin=".8s" repeatCount="indefinite">
            <mpath href="#pa" />
          </animateMotion>
        </circle>
      </g>
      <g fontFamily="Inter Variable, Inter, system-ui, sans-serif" fontSize="14" fontWeight="600" textAnchor="middle">
        <text x="480" y="34" textAnchor="start" fill="#8B98F5" fontSize="13">{t("flowFast")}</text>
        <text x="480" y="362" textAnchor="start" fill="#E0A458" fontSize="13">{t("flowAgent")}</text>
        <rect x="20" y="158" width="150" height="64" rx="14" fill="#1E2029" stroke="#3A3D4D" />
        <text x="95" y="186" fill="#fff">{t("flowQuestion")}</text>
        <text x="95" y="206" fill="#8D8FA0" fontSize="12" fontWeight="400">{t("flowQuestionExample")}</text>
        <rect x="240" y="158" width="150" height="64" rx="14" fill="#262A4A" stroke="#5E6BD6" />
        <text x="315" y="186" fill="#fff">{t("flowRouter")}</text>
        <text x="315" y="206" fill="#A9B1F2" fontSize="12" fontWeight="400">{t("flowRouterSub")}</text>
        <rect x="480" y="54" width="140" height="52" rx="12" fill="#1E2029" stroke="#3A3D4D" />
        <text x="550" y="85" fill="#fff">{t("flowSearch")}</text>
        <rect x="650" y="54" width="140" height="52" rx="12" fill="#1E2029" stroke="#3A3D4D" />
        <text x="720" y="85" fill="#fff">{t("flowRerank")}</text>
        <rect x="820" y="54" width="140" height="52" rx="12" fill="#1E2029" stroke="#3A3D4D" />
        <text x="890" y="85" fill="#fff">{t("flowGenerate")}</text>
        <rect x="480" y="274" width="140" height="52" rx="12" fill="#1E2029" stroke="#3A3D4D" />
        <text x="550" y="305" fill="#fff">{t("flowPlan")}</text>
        <rect x="650" y="274" width="140" height="52" rx="12" fill="#1E2029" stroke="#3A3D4D" />
        <text x="720" y="305" fill="#fff">{t("flowTools")}</text>
        <rect x="820" y="274" width="140" height="52" rx="12" fill="#2E2618" stroke="#8A6A3A" />
        <text x="890" y="305" fill="#FCE3BF">{t("flowApproval")}</text>
        <rect x="1010" y="152" width="172" height="76" rx="16" fill="#18352A" stroke="#3F9A6E" />
        <text x="1096" y="184" fill="#fff">{t("flowAnswer")}</text>
        <text x="1096" y="206" fill="#8FD9B4" fontSize="12" fontWeight="400">{t("flowAnswerSub")}</text>
      </g>
    </svg>
  );
}

export default async function LandingPage() {
  const t = await getTranslations("landing");
  const brand = (await getTranslations("common"))("brand");
  const guarantees = t.raw("guarantees") as { value: string; label: string }[];
  const how = t.raw("how") as { title: string; body: string }[];
  const security = t.raw("security") as string[];
  const vault = t.raw("vault") as { label: string; value: string }[];
  const howLinks = ["/admin/sources/new", "/admin/chatbots/new/pipeline", "/admin/chatbots/new/access", "/admin/chatbots/new/publish"];

  return (
    <div className="relative bg-ground text-fg">
      <header className="absolute inset-x-0 top-0 z-10 text-white">
        <div className="mx-auto box-border max-w-[1240px] px-8 max-[640px]:px-4">
          <div className="flex h-[76px] flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <BrandMark inverted className="size-[34px] rounded-[9px] text-[15px] font-extrabold" />
              <div className="text-base font-bold">{brand}</div>
            </div>
            <nav aria-label={t("navLabel")} className="flex gap-7 text-sm max-[900px]:hidden">
              <a href="#features" className="text-hero-muted no-underline hover:text-white">{t("nav.features")}</a>
              <a href="#how" className="text-hero-muted no-underline hover:text-white">{t("nav.how")}</a>
              <a href="#chatbots" className="text-hero-muted no-underline hover:text-white">{t("nav.chatbots")}</a>
              <a href="#security" className="text-hero-muted no-underline hover:text-white">{t("nav.security")}</a>
              <Link href="/status" className="text-hero-muted no-underline hover:text-white">{t("nav.status")}</Link>
            </nav>
            <div className="flex gap-2.5">
              <Link className={btnOutline} href="/sign-in">{t("signIn")}</Link>
              <Link className={btnLight} href="/admin">{t("ctaAdmin")}</Link>
            </div>
          </div>
        </div>
      </header>
      <main id="main">
      <div className="relative overflow-hidden bg-hero pt-[76px] pb-[72px] text-white">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 [background-image:radial-gradient(rgba(255,255,255,.07)_1px,transparent_1px)] [background-size:24px_24px] [mask-image:linear-gradient(#000,transparent_85%)]" />
        <div aria-hidden="true" className="pointer-events-none absolute -top-[260px] -right-[160px] size-[720px] rounded-full bg-[radial-gradient(circle,rgba(51,69,184,.55),transparent_65%)] [animation:vey-drift_12s_ease-in-out_infinite_alternate]" />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-[260px] -left-[120px] size-[520px] rounded-full bg-[radial-gradient(circle,rgba(30,107,69,.35),transparent_65%)] [animation:vey-drift_14s_ease-in-out_infinite_alternate-reverse]" />
        <div className="relative mx-auto box-border max-w-[1240px] px-8 max-[640px]:px-4">
          <div className="pt-16">
            <span className="inline-flex h-[30px] items-center gap-2 rounded-[15px] border border-[rgba(139,152,245,.3)] bg-[rgba(139,152,245,.12)] px-3 text-[13px] font-medium text-[#C9CEFA]">
              <span className="size-[7px] rounded-full bg-hero-green [animation:vey-ping_2s_infinite]" />
              {t("pill")}
            </span>
            <h1 className="mt-[22px] mb-[18px] max-w-[900px] text-[64px] leading-[1.04] font-extrabold tracking-[-0.035em] max-[640px]:text-[40px]">
              {t("headline1")}
              <br />
              <span className="bg-[linear-gradient(90deg,#8B98F5,#5DD39E)] bg-clip-text text-transparent">{t("headline2")}</span>
            </h1>
            <p className="m-0 mb-[30px] max-w-[640px] text-[19px] leading-[1.55] text-hero-muted">{t("sub")}</p>
            <div className="flex flex-wrap gap-3">
              <Link className={btnLight} href="/home">
                {t("ctaChat")} <span aria-hidden="true">→</span>
              </Link>
              <Link className={btnOutline} href="/admin/chatbots/new">{t("ctaBuild")}</Link>
              <Link className={btnOutline} href="/admin/pipelines">{t("ctaPipeline")}</Link>
            </div>
          </div>

          <div className="relative mt-14 rounded-[20px] border border-[#2A2C38] bg-[linear-gradient(180deg,rgba(255,255,255,.04),rgba(255,255,255,.015))] px-[22px] pt-[22px] pb-2.5">
            <div className="mb-1.5 flex items-center justify-between text-[13px] text-[#8D8FA0]">
              <span>{t("flowTitle")}</span>
              <span className="font-mono">{t("flowExample")}</span>
            </div>
            <RequestFlow t={t} />
          </div>
        </div>
      </div>

      <div className="mx-auto box-border max-w-[1240px] px-8 max-[640px]:px-4">
        <ul className="relative m-0 -mt-10 grid list-none grid-cols-4 gap-4 p-0 max-[900px]:grid-cols-2">
          {guarantees.map((g) => (
            <li key={g.label} className="rounded-xl border border-line bg-surface px-6 py-[22px] shadow-[0_10px_30px_rgba(18,19,24,.06)]">
              <b className="block text-[34px] tracking-[-0.02em]">{g.value}</b>
              <span className="text-sm text-fg-muted">{g.label}</span>
            </li>
          ))}
        </ul>

        <section className="pt-24" id="features">
          <div className="text-[13px] font-semibold tracking-[0.1em] text-accent uppercase">{t("featuresEyebrow")}</div>
          <h2 className="mt-2.5 mb-3.5 text-[42px] leading-[1.1] font-extrabold tracking-[-0.03em] max-[640px]:text-[30px]">{t("featuresTitle")}</h2>
          <p className="m-0 max-w-[640px] text-[17px] leading-[1.55] text-fg-muted">{t("featuresLead")}</p>
          <div className="mt-10 grid grid-cols-3 gap-[18px] max-[900px]:grid-cols-1">
            <FeatureCard
              href="/admin/pipelines"
              className="col-span-2 max-[900px]:col-span-1"
              title={t("features.router.title")}
              body={t("features.router.body")}
              more={t("features.router.more")}
              icon={<Icon bg="var(--vey-accent-soft-strong)" stroke="var(--vey-accent)"><path d="M4 12h6M10 12l6-6h4M10 12l6 6h4" /></Icon>}
            >
              <div className="mt-1 flex flex-wrap items-center gap-2.5">
                <span className="inline-flex h-6 items-center rounded-xl bg-accent-soft-strong px-2.5 text-xs font-semibold text-accent">{t("features.router.fast")}</span>
                <span className="inline-flex h-6 items-center rounded-xl bg-sunken px-2.5 text-xs font-semibold text-fg-secondary">{t("features.router.auto")}</span>
                <span className="inline-flex h-6 items-center rounded-xl bg-amber-soft px-2.5 text-xs font-semibold text-amber">{t("features.router.agent")}</span>
              </div>
            </FeatureCard>
            <FeatureCard href="/admin/chatbots" title={t("features.flow.title")} body={t("features.flow.body")} more={t("features.flow.more")}
              icon={<Icon bg="var(--vey-green-soft)" stroke="var(--vey-green)"><rect x="3" y="4" width="7" height="6" rx="1.5" /><rect x="14" y="14" width="7" height="6" rx="1.5" /><path d="M10 7h4a3 3 0 0 1 3 3v4" /></Icon>} />
            <FeatureCard href="/admin/chatbots" title={t("features.bots.title")} body={t("features.bots.body")} more={t("features.bots.more")}
              icon={<Icon bg="var(--vey-amber-soft)" stroke="var(--vey-amber)"><rect x="4" y="7" width="16" height="12" rx="3" /><path d="M12 3v4M9 13h.01M15 13h.01" /></Icon>} />
            <FeatureCard href="/admin/providers" title={t("features.providers.title")} body={t("features.providers.body")} more={t("features.providers.more")}
              icon={<Icon bg="var(--vey-accent-soft-strong)" stroke="var(--vey-accent)"><circle cx="8" cy="15" r="4" /><path d="M11 12l8-8M16 7l2 2M14 9l2 2" /></Icon>} />
            <FeatureCard href="/admin/tools" title={t("features.tools.title")} body={t("features.tools.body")} more={t("features.tools.more")}
              icon={<Icon bg="var(--vey-green-soft)" stroke="var(--vey-green)"><path d="M14 6l4 4-8 8H6v-4z" /><path d="M12 8l4 4" /></Icon>} />
            <FeatureCard href="/admin/automations" title={t("features.automations.title")} body={t("features.automations.body")} more={t("features.automations.more")}
              icon={<Icon bg="var(--vey-amber-soft)" stroke="var(--vey-amber)"><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></Icon>} />
            <FeatureCard href="/admin/knowledge-health" title={t("features.health.title")} body={t("features.health.body")} more={t("features.health.more")}
              icon={<Icon bg="var(--vey-red-soft)" stroke="var(--vey-red)"><path d="M3 12h4l2-5 4 10 2-5h6" /></Icon>} />
            <FeatureCard href="/admin/channels" title={t("features.channels.title")} body={t("features.channels.body")} more={t("features.channels.more")}
              icon={<Icon bg="var(--vey-accent-soft-strong)" stroke="var(--vey-accent)"><path d="M4 5h16v11H9l-5 4z" /></Icon>} />
            <Link href="/admin/evaluation" className={`${card} group col-span-3 flex-row items-stretch gap-7 max-[900px]:col-span-1 max-[900px]:flex-col`}>
              <div className="flex flex-1 flex-col gap-3">
                <Icon bg="var(--vey-accent-soft-strong)" stroke="var(--vey-accent)"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Icon>
                <h3 className="m-0 text-[19px] tracking-[-0.01em]">{t("features.eval.title")}</h3>
                <p className="m-0 text-[14.5px] leading-normal text-fg-muted">{t("features.eval.body")}</p>
                <span className="mt-auto text-sm font-semibold text-accent group-hover:underline">{t("features.eval.more")}</span>
              </div>
              {/* The real publish gate from the brief, not sample scores. */}
              <div className="flex w-[390px] max-w-full flex-col justify-center gap-3 rounded-xl bg-sunken p-5">
                <span className="text-xs font-semibold tracking-wide text-fg-muted uppercase">{t("features.eval.gateTitle")}</span>
                {[
                  { label: t("features.eval.faithfulness"), value: 0.85 },
                  { label: t("features.eval.relevance"), value: 0.8 },
                ].map((g) => (
                  <div key={g.label} className="flex flex-col gap-1">
                    <div className="flex justify-between text-sm">
                      <span>{g.label}</span>
                      <span className="font-mono font-semibold">≥ {g.value.toFixed(2)}</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded bg-line">
                      <div className="h-full bg-accent" style={{ width: `${g.value * 100}%` }} />
                    </div>
                  </div>
                ))}
                <span className="text-xs text-fg-muted">{t("features.eval.gateNote")}</span>
              </div>
            </Link>
          </div>
        </section>

        <section className="pt-24" id="how">
          <div className="text-[13px] font-semibold tracking-[0.1em] text-accent uppercase">{t("howEyebrow")}</div>
          <h2 className="mt-2.5 mb-3.5 text-[42px] leading-[1.1] font-extrabold tracking-[-0.03em] max-[640px]:text-[30px]">{t("howTitle")}</h2>
          <ol className="relative m-0 mt-11 grid list-none grid-cols-4 gap-[18px] p-0 max-[900px]:grid-cols-2">
            <svg aria-hidden="true" className="absolute top-[27px] left-[12%] h-1 w-[76%] overflow-visible max-[900px]:hidden" viewBox="0 0 100 4" preserveAspectRatio="none">
              <path d="M0 2H100" stroke="var(--vey-accent)" strokeWidth="2" className="vey-march" vectorEffect="non-scaling-stroke" />
            </svg>
            {how.map((step, i) => (
              <li key={step.title}>
                <Link href={howLinks[i] ?? "/admin"} className="group relative flex flex-col items-center gap-2.5 text-center !text-fg no-underline">
                  <span className="flex size-14 items-center justify-center rounded-full border-2 border-accent bg-surface text-xl font-extrabold text-accent shadow-[0_0_0_6px_var(--vey-ground)] group-hover:bg-accent group-hover:text-on-accent">
                    {i + 1}
                  </span>
                  <h3 className="mt-1.5 mb-0 text-[17px]">{step.title}</h3>
                  <p className="m-0 max-w-[240px] text-sm leading-normal text-fg-muted">{step.body}</p>
                </Link>
              </li>
            ))}
          </ol>
        </section>

        <section className="pt-24" id="chatbots">
          <div className="text-[13px] font-semibold tracking-[0.1em] text-accent uppercase">{t("botsEyebrow")}</div>
          <h2 className="mt-2.5 mb-3.5 text-[42px] leading-[1.1] font-extrabold tracking-[-0.03em] max-[640px]:text-[30px]">{t("botsTitle")}</h2>
          <div className="mt-10 grid grid-cols-4 gap-4 max-[900px]:grid-cols-2 max-[640px]:grid-cols-1">
            {(
              [
                { id: "faq", av: "FAQ", bg: "var(--vey-accent)", tag: "bg-accent-soft-strong text-accent" },
                { id: "support", av: "SA", bg: "var(--vey-green)", tag: "bg-sunken text-fg-secondary" },
                { id: "research", av: "RA", bg: "var(--vey-amber)", tag: "bg-amber-soft text-amber" },
              ] as const
            ).map((tpl) => (
              <Link key={tpl.id} href={`/admin/chatbots/new?template=${tpl.id}`} className="flex flex-col gap-2.5 rounded-xl border border-line bg-surface p-5 !text-fg no-underline hover:border-accent">
                <span className="flex size-10 items-center justify-center rounded-[10px] text-xs font-bold text-ground" style={{ background: tpl.bg }}>{tpl.av}</span>
                <b>{t(`templates.${tpl.id}.name`)}</b>
                <span className="text-[13.5px] text-fg-muted">{t(`templates.${tpl.id}.body`)}</span>
                <span className={`inline-flex h-6 w-fit items-center rounded-xl px-2.5 text-xs font-semibold ${tpl.tag}`}>{t(`templates.${tpl.id}.tag`)}</span>
              </Link>
            ))}
            <Link href="/admin/chatbots/new" className="flex flex-col items-center justify-center gap-2.5 rounded-xl border border-dashed border-line-strong bg-surface p-5 text-center !text-accent no-underline hover:border-accent">
              <span aria-hidden="true" className="flex size-10 items-center justify-center rounded-[10px] bg-accent-soft-strong text-[22px] font-bold text-accent">+</span>
              <b>{t("templates.new.name")}</b>
              <span className="text-[13.5px] text-fg-muted">{t("templates.new.body")}</span>
            </Link>
          </div>
        </section>

        <section className="pt-24" id="security">
          <div className="grid grid-cols-[1.1fr_1fr] items-center gap-12 rounded-[28px] bg-hero p-14 text-white max-[900px]:grid-cols-1 max-[640px]:p-7">
            <div>
              <div className="text-[13px] font-semibold tracking-[0.1em] text-hero-accent uppercase">{t("securityEyebrow")}</div>
              <h2 className="mt-2.5 mb-3.5 text-[42px] leading-[1.1] font-extrabold tracking-[-0.03em] text-white max-[640px]:text-[30px]">{t("securityTitle")}</h2>
              <ul className="m-0 mt-[22px] flex list-none flex-col gap-3.5 p-0">
                {security.map((line) => (
                  <li key={line} className="flex items-start gap-3 text-[15px] leading-normal text-[#D3D4DE]">
                    <i aria-hidden="true" className="mt-px flex size-[22px] flex-none items-center justify-center rounded-full bg-[rgba(93,211,158,.15)] text-[13px] font-bold text-hero-green not-italic">✓</i>
                    {line}
                  </li>
                ))}
              </ul>
              <div className="mt-7 flex gap-3">
                <Link className={btnLight} href="/admin/governance">{t("governance")}</Link>
                <Link className={btnOutline} href="/admin/audit">{t("auditLog")}</Link>
              </div>
            </div>
            <div className="rounded-xl border border-[#2A2C38] bg-[#1B1C23] p-5 text-[13px]">
              <div className="mb-1.5 flex justify-between text-[#8D8FA0]">
                <span>{t("vaultTitle")}</span>
                <span className="font-mono">{t("vaultMode")}</span>
              </div>
              <dl className="m-0">
                {vault.map((row) => (
                  <div key={row.label} className="flex items-center justify-between gap-3 border-b border-[#2A2C38] py-[11px] last:border-b-0">
                    <dt>{row.label}</dt>
                    <dd className="m-0 font-mono text-[#8FD9B4]">{row.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </section>

        <section className="relative mt-24 flex items-center justify-between gap-8 overflow-hidden rounded-[28px] bg-[linear-gradient(120deg,#3345B8,#1F2C80)] p-14 text-white after:absolute after:-top-20 after:-right-20 after:size-80 after:rounded-full after:border-[40px] after:border-white/[.07] after:content-[''] max-[900px]:flex-col max-[900px]:items-start max-[640px]:p-7">
          <div className="relative">
            <h2 className="m-0 mb-2 text-[42px] leading-[1.1] font-extrabold tracking-[-0.03em] text-white max-[640px]:text-[30px]">{t("ctaTitle")}</h2>
            <p className="m-0 text-[17px] text-[#D5D9F7]">{t("ctaBody")}</p>
          </div>
          <div className="relative flex gap-3">
            <Link className={btnLight} href="/sign-in">{t("ctaSignIn")}</Link>
            <Link className={`${btnOutline} border-white/40`} href="/admin">{t("ctaAdmin")}</Link>
          </div>
        </section>

        <footer className="flex flex-wrap justify-between gap-4 pt-10 pb-12 text-[13px] text-fg-muted">
          <span>{t("footer")}</span>
          <span className="flex gap-5">
            <Link href="/help" className="text-fg-muted hover:text-fg">{t("footerHelp")}</Link>
            <Link href="/status" className="text-fg-muted hover:text-fg">{t("footerStatus")}</Link>
            <Link href="/help#privacy" className="text-fg-muted hover:text-fg">{t("footerPrivacy")}</Link>
          </span>
        </footer>
      </div>
      </main>
    </div>
  );
}
