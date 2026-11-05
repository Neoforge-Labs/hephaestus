package ingot

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func write(t *testing.T, dir, body string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, "heph.toml"), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestLoadMissingNamesFileAndDir(t *testing.T) {
	dir := t.TempDir()
	_, err := Load(dir)
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "heph.toml") || !strings.Contains(err.Error(), dir) {
		t.Fatalf("error must name heph.toml and %s, got: %v", dir, err)
	}
}

func TestLoadValid(t *testing.T) {
	dir := t.TempDir()
	write(t, dir, "[ingot]\nname = \"hello\"\n[dev]\nfragments = [\"telemetry\", \"postgres\"]\n")
	cfg, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Ingot.Name != "hello" || len(cfg.Dev.Fragments) != 2 || cfg.Dev.Fragments[1] != "postgres" {
		t.Fatalf("unexpected config: %+v", cfg)
	}
}

func TestLoadRejects(t *testing.T) {
	cases := map[string]struct{ body, want string }{
		"malformed toml":     {"[ingot\nname=", "heph.toml"},
		"missing name":       {"[dev]\nfragments = [\"telemetry\"]\n", "ingot.name"},
		"invalid name":       {"[ingot]\nname = \"Hello World\"\n[dev]\nfragments = [\"telemetry\"]\n", "ingot.name"},
		"no fragments":       {"[ingot]\nname = \"hello\"\n", "dev.fragments"},
		"unknown key":        {"[ingot]\nname = \"hello\"\n[dev]\nfragmnts = [\"x\"]\nfragments = [\"telemetry\"]\n", "fragmnts"},
		"duplicate fragment": {"[ingot]\nname = \"hello\"\n[dev]\nfragments = [\"telemetry\", \"telemetry\"]\n", "duplicate"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			write(t, dir, c.body)
			_, err := Load(dir)
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("want error containing %q, got %v", c.want, err)
			}
		})
	}
}
