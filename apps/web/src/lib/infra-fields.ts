/**
 * The six services Veyntora runs on and the fields each one asks for (ADR 0034): shared by
 * the Setup page and Admin → Infrastructure. Labels live in messages under `infra.fields`.
 */

export type InfraService = "postgres" | "valkey" | "s3" | "openbao" | "openfga" | "keycloak";

export const INFRA_SERVICES: readonly InfraService[] = [
  "postgres",
  "valkey",
  "s3",
  "openbao",
  "openfga",
  "keycloak",
];

export type Field = {
  name: string;
  kind: "text" | "number" | "bool";
  initial: string | number | boolean;
  placeholder?: string;
  required?: boolean;
};

/** Passwords by name, as the API stores them (kv/veyntora/infra/<name>). */
export type SecretField = { name: string; optional?: boolean };

export const FIELDS: Record<InfraService, Field[]> = {
  postgres: [
    {
      name: "host",
      kind: "text",
      initial: "",
      placeholder: "host.docker.internal",
      required: true,
    },
    { name: "port", kind: "number", initial: 5432 },
    { name: "database", kind: "text", initial: "veyntora" },
    { name: "owner_user", kind: "text", initial: "veyntora" },
    { name: "user", kind: "text", initial: "veyntora_runtime" },
    { name: "aegra_database", kind: "text", initial: "aegra" },
    { name: "aegra_user", kind: "text", initial: "aegra" },
    { name: "ssl", kind: "bool", initial: false },
  ],
  valkey: [
    {
      name: "host",
      kind: "text",
      initial: "",
      placeholder: "host.docker.internal",
      required: true,
    },
    { name: "port", kind: "number", initial: 6379 },
    { name: "username", kind: "text", initial: "" },
    { name: "db", kind: "number", initial: 0 },
    { name: "graphs_db", kind: "number", initial: 2 },
    { name: "tls", kind: "bool", initial: false },
  ],
  s3: [
    {
      name: "endpoint",
      kind: "text",
      initial: "",
      placeholder: "http://host.docker.internal:8333",
      required: true,
    },
    { name: "region", kind: "text", initial: "eu-central-1" },
    { name: "bucket", kind: "text", initial: "veyntora" },
    { name: "audit_bucket", kind: "text", initial: "veyntora-audit" },
    { name: "access_key", kind: "text", initial: "", required: true },
  ],
  openbao: [
    {
      name: "url",
      kind: "text",
      initial: "",
      placeholder: "http://host.docker.internal:8200",
      required: true,
    },
    { name: "kv_mount", kind: "text", initial: "kv" },
  ],
  openfga: [
    {
      name: "url",
      kind: "text",
      initial: "",
      placeholder: "http://host.docker.internal:8080",
      required: true,
    },
    { name: "store_name", kind: "text", initial: "veyntora" },
  ],
  keycloak: [
    {
      name: "issuer",
      kind: "text",
      initial: "",
      placeholder: "http://localhost:8080/realms/veyntora",
      required: true,
    },
    {
      name: "internal_base",
      kind: "text",
      initial: "",
      placeholder: "http://host.docker.internal:8080/realms/veyntora",
    },
    { name: "client_id", kind: "text", initial: "veyntora" },
    { name: "sync_client_id", kind: "text", initial: "veyntora-sync" },
  ],
};

export const SECRETS: Record<InfraService, SecretField[]> = {
  postgres: [
    { name: "postgres-owner-password" },
    { name: "postgres-password" },
    { name: "postgres-aegra-password" },
  ],
  valkey: [{ name: "valkey-password", optional: true }],
  s3: [{ name: "s3-secret-key" }],
  openbao: [],
  openfga: [],
  keycloak: [{ name: "keycloak-client-secret" }, { name: "keycloak-sync-client-secret" }],
};

export type Values = Record<string, string | number | boolean>;

export function initialValues(
  service: InfraService,
  saved?: Record<string, unknown> | null,
): Values {
  return Object.fromEntries(
    FIELDS[service].map((f) => {
      const v = saved?.[f.name];
      return [f.name, v === undefined || v === null ? f.initial : (v as string | number | boolean)];
    }),
  );
}

/** Form values as the API expects them: numbers as numbers, empty optional text left out. */
export function toSettings(service: InfraService, values: Values): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of FIELDS[service]) {
    const v = values[f.name];
    if (f.kind === "number") out[f.name] = Number(v);
    else if (f.kind === "bool") out[f.name] = Boolean(v);
    else out[f.name] = String(v ?? "").trim();
  }
  return out;
}
