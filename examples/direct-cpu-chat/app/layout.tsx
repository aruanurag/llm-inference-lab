import "./styles.css";

export const metadata = {
  title: "Direct CPU Chat",
  description: "Hackathon sample app calling the OCI CPU inference endpoint directly.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
