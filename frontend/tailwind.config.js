/** @type {import('tailwindcss').Config} */
// shadcn/ui 토큰 계약 — 값은 Report Archive(사내 웹)와 같게 둔다. 사용자가 "그 느낌" 이라 한 것이
// 이 스택의 언어이고, 같은 값을 쓰면 두 앱을 오가는 사람이 조작법을 다시 배우지 않는다.
//
// preflight 를 켰다(2026-10-07). 도입 당시에는 기존 `rr-*` 608줄이 화면 대부분을 그리고 있어
// base reset 이 들어오면 한꺼번에 무너졌으므로 꺼 두고 시작했다. 화면 일곱을 모두 옮겨 레거시
// 클래스의 마지막 사용자가 사라져 이제 켠다 — 점진 도입의 예정된 종점이다.
//
// 켜지 않고 둔 대가가 작지 않았다. preflight 가 주는 `border-style: solid` 가 없어 앱의
// `border-*` 유틸이 **전부 무효**였고(선이 하나도 안 그려졌다), <h2>·<p> 의 UA margin 이 살아
// 있어 카드 머리말이 헐거웠다. 둘 다 조용한 결함이라 띄워 보기 전에는 드러나지 않았다.
export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
    extend: {
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "Noto Sans KR", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "Noto Sans Mono", "monospace"],
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        // 판정 색 — 이 앱은 '괜찮다·조건부·막혔다' 를 늘 말해야 한다(§2.12 게이트·§4 등급).
        // shadcn 기본에는 없어서 더한다. destructive 와 섞지 않는다(그건 '파괴적 조작' 용이다).
        ok: { DEFAULT: "hsl(var(--ok))", foreground: "hsl(var(--ok-foreground))" },
        warn: { DEFAULT: "hsl(var(--warn))", foreground: "hsl(var(--warn-foreground))" },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
