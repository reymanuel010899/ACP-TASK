export default function SlackBrandIcon({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      data-testid="slack-brand-icon"
      aria-hidden="true"
      viewBox="0 0 122.8 122.8"
      className={className}
    >
      <path fill="#E01E5A" d="M25.8 77.6a12.9 12.9 0 1 1-12.9-12.9h12.9v12.9Zm6.5 0a12.9 12.9 0 0 1 25.8 0v32.3a12.9 12.9 0 0 1-25.8 0V77.6Z" />
      <path fill="#36C5F0" d="M45.2 25.8a12.9 12.9 0 1 1 12.9-12.9v12.9H45.2Zm0 6.5a12.9 12.9 0 0 1 0 25.8H12.9a12.9 12.9 0 0 1 0-25.8h32.3Z" />
      <path fill="#2EB67D" d="M97 45.2a12.9 12.9 0 1 1 12.9 12.9H97V45.2Zm-6.5 0a12.9 12.9 0 0 1-25.8 0V12.9a12.9 12.9 0 0 1 25.8 0v32.3Z" />
      <path fill="#ECB22E" d="M77.6 97a12.9 12.9 0 1 1-12.9 12.9V97h12.9Zm0-6.5a12.9 12.9 0 0 1 0-25.8h32.3a12.9 12.9 0 0 1 0 25.8H77.6Z" />
    </svg>
  );
}
