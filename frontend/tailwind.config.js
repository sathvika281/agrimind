/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Deep forest greens (sidebar, active states, primary actions) down to pale tints.
        leaf: {
          50: "#eef4ef",
          100: "#d9e8dd",
          200: "#b9d6c1",
          500: "#3f8a5a",
          600: "#1d5a3e",
          700: "#16482f",
          800: "#123c2c",
          900: "#0d2d21",
        },
        mint: { 100: "#c4f1d6", 200: "#a9e8c3", 700: "#14573a" },
        ground: "#f3f2ed", // warm off-white page
        line: "#e3e1d9", // thin borders
        ink: "#1b2a23", // charcoal-green text
        mute: "#66726b", // secondary text
        stress: "#e58f3d", // orange: stress
        warn: "#d9a233", // amber: attention
        crit: "#b4443a", // red: critical
        water: "#3a82a8", // blue: water/weather
      },
      fontFamily: {
        sans: ['"Segoe UI"', "system-ui", "-apple-system", "Roboto", '"Noto Sans Telugu"', "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Consolas", '"Liberation Mono"', "monospace"],
      },
      fontSize: { micro: ["0.75rem", { lineHeight: "1rem" }] }, // 12px floor (keeps Telugu legible)
      borderRadius: { panel: "8px" },
    },
  },
  plugins: [],
};
