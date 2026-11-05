package fragments

import (
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"testing/fstest"
)

func TestResolveUnknownListsAvailable(t *testing.T) {
	fsys := fstest.MapFS{
		"telemetry.yaml": {Data: []byte("services: {}\n")},
		"postgres.yaml":  {Data: []byte("services: {}\n")},
	}
	_, err := ResolveFrom(fsys, []string{"telemetry", "nope"})
	if err == nil {
		t.Fatal("expected error")
	}
	for _, want := range []string{`"nope"`, "postgres", "telemetry"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("error %q missing %q", err, want)
		}
	}
}

func TestResolveParsesHostPorts(t *testing.T) {
	fsys := fstest.MapFS{
		"a.yaml": {Data: []byte(`services:
  x:
    ports:
      - "54300:3000"
      - "127.0.0.1:54317:4317"
      - 54318:4318
      - "9999"
      - target: 80
        published: 54080
  y:
    ports: ["54081:81"]
`)},
	}
	got, err := ResolveFrom(fsys, []string{"a"})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Name != "a" || got[0].Path != "a.yaml" {
		t.Fatalf("unexpected: %+v", got)
	}
	// Ports is sorted ascending.
	want := []int{54080, 54081, 54300, 54317, 54318}
	if !reflect.DeepEqual(got[0].Ports, want) {
		t.Fatalf("ports = %v, want %v", got[0].Ports, want)
	}
}

func TestResolveMalformed(t *testing.T) {
	cases := map[string]string{
		"bad yaml":     "services: [\n",
		"bad port":     "services:\n  x:\n    ports: [\"abc:80\"]\n",
		"range port":   "services:\n  x:\n    ports: [\"8000-8010:80\"]\n",
		"interpolated": "services:\n  x:\n    ports: [\"${P}:80\"]\n",
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			fsys := fstest.MapFS{"m.yaml": {Data: []byte(body)}}
			_, err := ResolveFrom(fsys, []string{"m"})
			if err == nil || !strings.Contains(err.Error(), "m.yaml") {
				t.Fatalf("want error naming m.yaml, got %v", err)
			}
		})
	}
}

// The real fragments in compose/ are the source of truth for ports. If Task 12
// changes one, this test follows it, because nothing here is hard-coded twice
// except the expectation below, which is the plan's fixed port block.
func TestResolveRealComposeFragments(t *testing.T) {
	src := filepath.Join("..", "..", "..", "compose")
	if _, err := os.Stat(src); err != nil {
		t.Skip("compose/ not found")
	}
	got, err := ResolveFrom(os.DirFS(src), []string{"postgres", "objects", "telemetry", "mail", "redis", "stripe"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string][]int{
		"postgres":  {54320},
		"objects":   {54333, 54334},
		"telemetry": {54300, 54317, 54318},
		"mail":      {54025, 54825},
		"redis":     {54379},
		"stripe":    nil,
	}
	for _, f := range got {
		if !reflect.DeepEqual(f.Ports, want[f.Name]) && !(len(f.Ports) == 0 && len(want[f.Name]) == 0) {
			t.Errorf("%s ports = %v, want %v", f.Name, f.Ports, want[f.Name])
		}
	}
}

func TestResolveEmbeddedUnsyncedSaysHowToFix(t *testing.T) {
	_, err := ResolveFrom(fstest.MapFS{}, []string{"telemetry"})
	if err == nil || !strings.Contains(err.Error(), "sync-fragments") {
		t.Fatalf("want hint about sync-fragments, got %v", err)
	}
}

func TestSyncAndCheck(t *testing.T) {
	src, dst := t.TempDir(), t.TempDir()
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(os.WriteFile(filepath.Join(src, "a.yaml"), []byte("a: 1\n"), 0o644))
	must(os.WriteFile(filepath.Join(src, "s.json"), []byte("{}\n"), 0o644))
	must(os.WriteFile(filepath.Join(src, "moon.yml"), []byte("x"), 0o644)) // not a fragment file
	must(os.MkdirAll(filepath.Join(src, "test"), 0o755))
	must(os.WriteFile(filepath.Join(src, "test", "boot_test.sh"), []byte("x"), 0o644))

	if err := Check(src, dst); err == nil {
		t.Fatal("check must fail before sync")
	}
	must(Sync(src, dst))
	must(Check(src, dst))
	if _, err := os.Stat(filepath.Join(dst, "moon.yml")); err == nil {
		t.Fatal("moon.yml must not be copied")
	}
	if _, err := os.Stat(filepath.Join(dst, "test")); err == nil {
		t.Fatal("test/ must not be copied")
	}

	// Drift: modified, extra, and missing files are each detected.
	must(os.WriteFile(filepath.Join(dst, "a.yaml"), []byte("a: 2\n"), 0o644))
	if err := Check(src, dst); err == nil || !strings.Contains(err.Error(), "a.yaml") {
		t.Fatalf("modified file not detected: %v", err)
	}
	must(Sync(src, dst))
	must(os.WriteFile(filepath.Join(dst, "extra.yaml"), []byte("x"), 0o644))
	if err := Check(src, dst); err == nil || !strings.Contains(err.Error(), "extra.yaml") {
		t.Fatalf("extra file not detected: %v", err)
	}
	must(Sync(src, dst)) // sync removes stale files
	must(Check(src, dst))
	must(os.Remove(filepath.Join(dst, "s.json")))
	if err := Check(src, dst); err == nil || !strings.Contains(err.Error(), "s.json") {
		t.Fatalf("missing file not detected: %v", err)
	}
}

// A binary built from exactly what git serves — which is what `go install` and
// a release build get — must carry the fragments. While files/ was gitignored
// this held for no binary but a developer's own, and no gate caught it: `heph
// dev up` answered "no fragments are embedded in this heph build: run `moon run
// heph-cli:sync-fragments` and rebuild", advice a `go install` user cannot act
// on. Unlike TestEmbeddedCopyMatchesCompose this needs no compose/ checkout, so
// it cannot skip.
func TestEmbeddedFragmentsShipInTheBinary(t *testing.T) {
	got, err := Available(Embedded())
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"mail", "objects", "postgres", "redis", "stripe", "telemetry"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("embedded fragments = %v, want %v", got, want)
	}
	// The support file objects.yaml bind-mounts must travel with them.
	if _, err := fs.ReadFile(Embedded(), "seaweedfs-s3.json"); err != nil {
		t.Fatalf("seaweedfs-s3.json is not embedded: %v", err)
	}
}

// Materialize owns its directory, so a fragment that a later heph no longer
// has must not be left looking current next to the ones Compose was given.
func TestMaterializePrunesStaleFiles(t *testing.T) {
	dir := t.TempDir()
	stale := filepath.Join(dir, "mail.yaml")
	if err := os.WriteFile(stale, []byte("services: {}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	sub := filepath.Join(dir, "data")
	if err := os.MkdirAll(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	fsys := fstest.MapFS{
		"telemetry.yaml":    {Data: []byte("services:\n  g:\n    ports: [\"54300:3000\"]\n")},
		"seaweedfs-s3.json": {Data: []byte("{}\n")},
	}
	frs, err := ResolveFrom(fsys, []string{"telemetry"})
	if err != nil {
		t.Fatal(err)
	}
	paths, err := Materialize(fsys, dir, frs)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 1 || filepath.Base(paths[0]) != "telemetry.yaml" {
		t.Fatalf("selected paths = %v", paths)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Errorf("stale mail.yaml survived: %v", err)
	}
	for _, name := range []string{"telemetry.yaml", "seaweedfs-s3.json"} {
		if _, err := os.Stat(filepath.Join(dir, name)); err != nil {
			t.Errorf("%s was not written: %v", name, err)
		}
	}
	if _, err := os.Stat(sub); err != nil {
		t.Errorf("a subdirectory must never be pruned: %v", err)
	}
}

// The embedded copy is what ships in the binary. If it differs from compose/,
// the binary would run stale fragments, so go test fails until it is re-synced.
func TestEmbeddedCopyMatchesCompose(t *testing.T) {
	src := filepath.Join("..", "..", "..", "compose")
	if _, err := os.Stat(src); err != nil {
		t.Skip("compose/ not found")
	}
	if err := Check(src, "files"); err != nil {
		t.Fatal(err)
	}
}
