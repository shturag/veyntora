/**
 * A formatted date as every engine writes it. Node (the server) and WebKit (Safari) format
 * the same date with different spaces (U+202F before "PM") and joiners ("Nov 9, 2026 at
 * 10:58 PM", "Mo. 9. Nov." for "Mo., 9. Nov."), so text formatted in client components would
 * differ between the server's render and the browser's, and React would throw the page away
 * (error 418).
 */
export function sameText(formatted: string): string {
  return (
    formatted
      .replace(/[\u202f\u00a0]/g, " ")
      .replace(/ (at|um) (?=\d)/g, ", ")
      // A leading weekday: "Mo., 9. Nov." (Node) and "Mo. 9. Nov." (WebKit).
      .replace(/^(\p{L}+\.?), /u, "$1 ")
  );
}
