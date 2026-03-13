/** @type {import('tailwindcss').Config} */

//https://dribbble.com/shots/4435214-Green-Color-Palette
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#EBF2F3',
        secondary: '#E5EEEF',
        dark: '#1F6C75',
        accent: '#87E4DB',
        surface : '#CAF0C1',
        surfaceDark : '#00ACB1',
      },
      keyframes: {
        'voice-wave': {
          '0%, 100%': { height: '0.5rem' },
          '50%': { height: '3rem' },
        },
      },
      animation: {
        'voice-wave': 'voice-wave 0.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
