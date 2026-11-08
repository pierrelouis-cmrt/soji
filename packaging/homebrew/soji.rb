# Template for the tap repository (github.com/pierrelouis-cmrt/homebrew-tap,
# file Formula/soji.rb). `python3 build_release.py` writes a filled-in copy to
# dist/soji.rb; @VERSION@, @SHA256@ and @REPO@ are replaced there.
class Soji < Formula
  desc "Disk cleanup for macOS in the terminal, with layered safety checks"
  homepage "https://github.com/@REPO@"
  url "https://github.com/@REPO@/releases/download/v@VERSION@/soji.pyz"
  version "@VERSION@"
  sha256 "@SHA256@"

  depends_on :macos
  # 3.14+ adds compression.zstd, used to read compressed Codex sessions.
  depends_on "python@3.14"

  def install
    libexec.install "soji.pyz"
    (bin/"soji").write <<~SH
      #!/bin/sh
      exec "#{Formula["python@3.14"].opt_bin}/python3.14" "#{libexec}/soji.pyz" "$@"
    SH
    chmod 0755, bin/"soji"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/soji --version")
  end
end
