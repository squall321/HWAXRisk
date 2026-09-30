/** @type {import('tailwindcss').Config} */
// shadcn/ui 토큰 계약 — 값은 Report Archive(사내 웹)와 같게 둔다. 사용자가 "그 느낌" 이라 한 것이
// 이 스택의 언어이고, 같은 값을 쓰면 두 앱을 오가는 사람이 조작법을 다시 배우지 않는다.
//
// ⚠ preflight 를 끈다. 기존 index.css(608줄, `rr-*`)가 아직 화면 대부분을 그리는데 Tailwind 의
// base reset 이 들어오면 그 스타일이 한꺼번에 무너진다. 유틸리티만 켜서 새 컴포넌트부터 쓰고,
// 화면을 옮겨 가며 `rr-*` 를 걷어낸 뒤 그때 preflight 를 켠다(점진 도입의 표준 경로).
export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  corePlugins: { preflight: false },
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
