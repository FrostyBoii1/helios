/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // SunCentral dark brand palette (semantic tokens).
        bg: '#0F1011', // app background — near-black charcoal
        surface: '#18191C', // cards, header, tables
        elevated: '#212327', // inputs, hover, raised surfaces
        line: {
          DEFAULT: '#2A2C31', // subtle borders/dividers
          strong: '#3A3D43', // emphasized borders
        },
        fg: '#F4F4F3', // primary text (off-white)
        muted: '#9BA1A9', // secondary text
        faint: '#6A7079', // tertiary text / placeholders
        brand: {
          400: '#F7A23F',
          500: '#F2871E', // primary accent (SunCentral orange)
          600: '#D9740F', // hover
          DEFAULT: '#F2871E',
        },
        onbrand: '#14110D', // dark text on orange fills
      },
    },
  },
  plugins: [],
}
