import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

import { isLocale, LOCALE_COOKIE, negotiate } from "./config";

export default getRequestConfig(async () => {
  const cookieLocale = (await cookies()).get(LOCALE_COOKIE)?.value;
  const locale = isLocale(cookieLocale)
    ? cookieLocale
    : negotiate((await headers()).get("accept-language"));
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
    timeZone: "Europe/Berlin",
  };
});
