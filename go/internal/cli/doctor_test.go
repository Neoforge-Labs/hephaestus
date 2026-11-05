package cli

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/Neoforge-Labs/hephaestus/go/internal/compose"
)

// fakeEnv simulates the host toolchain without touching real Docker.
type fakeEnv struct {
	onPath  map[string]bool
	outputs map[string]fakeResult // key: "name arg arg"
}

type fakeResult struct {
	out string
	err error
}

func (f fakeEnv) LookPath(name string) (string, error) {
	if f.onPath[name] {
		return "/usr/local/bin/" + name, nil
	}
	return "", errors.New("not found")
}

func (f fakeEnv) Output(_ context.Context, name string, args ...string) ([]byte, error) {
	key := name + " " + strings.Join(args, " ")
	r, ok := f.outputs[key]
	if !ok {
		return nil, fmt.Errorf("fakeEnv: unexpected command %q", key)
	}
	return []byte(r.out), r.err
}

const (
	kDockerVersion  = "docker version --format {{.Client.Version}}"
	kComposeVersion = "docker compose version --short"
	kDockerInfo     = "docker info --format {{.ServerVersion}}"
)

func healthyEnv() fakeEnv {
	return fakeEnv{
		onPath: map[string]bool{"docker": true},
		outputs: map[string]fakeResult{
			kDockerVersion:  {out: "27.3.1\n"},
			kComposeVersion: {out: "v2.29.7\n"},
			kDockerInfo:     {out: "27.3.1\n"},
		},
	}
}

type fakeRunner struct{ calls [][]string }

func (r *fakeRunner) Run(_ context.Context, args []string) error {
	r.calls = append(r.calls, args)
	return nil
}

var _ compose.Runner = (*fakeRunner)(nil)

const hephToml = "[ingot]\nname = \"hello\"\n[dev]\nfragments = [\"telemetry\", \"postgres\"]\n"

var testFragments = fstest.MapFS{
	"telemetry.yaml": {Data: []byte("services:\n  otel:\n    ports: [\"54300:3000\", \"54317:4317\", \"54318:4318\"]\n")},
	"postgres.yaml":  {Data: []byte("services:\n  pg:\n    ports: [\"54320:5432\"]\n")},
	"objects.yaml":   {Data: []byte("services:\n  s3:\n    ports: [\"54333:8333\"]\n    volumes: [\"./s.json:/s.json\"]\n")},
	"s.json":         {Data: []byte("{}")},
	"broken.yaml":    {Data: []byte("services: [\n")},
}

type harness struct {
	deps   Deps
	runner *fakeRunner
	out    *bytes.Buffer
	errb   *bytes.Buffer
	state  string
}

func newHarness(t *testing.T, env fakeEnv, toml string) *harness {
	t.Helper()
	dir := t.TempDir()
	if toml != "" {
		if err := os.WriteFile(filepath.Join(dir, "heph.toml"), []byte(toml), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	h := &harness{runner: &fakeRunner{}, out: &bytes.Buffer{}, errb: &bytes.Buffer{}, state: filepath.Join(t.TempDir(), "state")}
	h.deps = Deps{
		Env: env, Runner: h.runner, Dir: dir, StateDir: h.state, Fragments: testFragments,
		PortInUse: func(int) bool { return false },
		Out:       h.out, Err: h.errb,
	}
	return h
}

func (h *harness) run(args ...string) int { return Execute(context.Background(), h.deps, args) }

func TestDoctorDockerMissing(t *testing.T) {
	h := newHarness(t, fakeEnv{onPath: map[string]bool{}}, "")
	if code := h.run("doctor"); code != 2 {
		t.Fatalf("exit = %d, want 2", code)
	}
	if !strings.Contains(h.errb.String(), "docker not found") {
		t.Fatalf("stderr = %q", h.errb.String())
	}
}

func TestDoctorComposeV1(t *testing.T) {
	cases := map[string]fakeResult{
		"plugin absent":  {err: errors.New("docker: 'compose' is not a docker command")},
		"reports v1":     {out: "1.29.2\n"},
		"reports old v2": {out: "v2.0.5\n"},
		"unparseable":    {out: "banana\n"},
	}
	for name, res := range cases {
		t.Run(name, func(t *testing.T) {
			env := healthyEnv()
			env.outputs[kComposeVersion] = res
			h := newHarness(t, env, "")
			if code := h.run("doctor"); code != 2 {
				t.Fatalf("exit = %d, want 2; stderr=%q", code, h.errb.String())
			}
			if !strings.Contains(h.errb.String(), "Compose v2") {
				t.Fatalf("stderr must name Compose v2, got %q", h.errb.String())
			}
		})
	}
}

func TestDoctorDockerTooOld(t *testing.T) {
	env := healthyEnv()
	env.outputs[kDockerVersion] = fakeResult{out: "19.03.8\n"}
	h := newHarness(t, env, "")
	if code := h.run("doctor"); code != 2 {
		t.Fatalf("exit = %d, want 2", code)
	}
	if !strings.Contains(h.errb.String(), "19.03.8") || !strings.Contains(h.errb.String(), "20.10") {
		t.Fatalf("stderr = %q", h.errb.String())
	}
}

func TestDoctorDaemonUnreachable(t *testing.T) {
	env := healthyEnv()
	env.outputs[kDockerInfo] = fakeResult{err: errors.New("Cannot connect to the Docker daemon")}
	h := newHarness(t, env, "")
	if code := h.run("doctor"); code != 2 {
		t.Fatalf("exit = %d, want 2", code)
	}
	if !strings.Contains(h.errb.String(), "daemon") {
		t.Fatalf("stderr = %q", h.errb.String())
	}
}

// `docker version` exits 1 with the client version on stdout when the daemon is
// down; doctor must report the daemon, not a confusing version failure.
func TestDoctorDaemonDownVersionExitsNonZero(t *testing.T) {
	env := healthyEnv()
	env.outputs[kDockerVersion] = fakeResult{out: "27.3.1\n", err: errors.New("exit status 1")}
	env.outputs[kDockerInfo] = fakeResult{err: errors.New("Cannot connect")}
	h := newHarness(t, env, "")
	if code := h.run("doctor"); code != 2 || !strings.Contains(h.errb.String(), "daemon") {
		t.Fatalf("exit=%d stderr=%q", code, h.errb.String())
	}
}

func TestDoctorHealthy(t *testing.T) {
	h := newHarness(t, healthyEnv(), "")
	if code := h.run("doctor"); code != 0 {
		t.Fatalf("exit = %d; stderr=%q", code, h.errb.String())
	}
}

// Real TCP listener, no fake: proves the default port check sees a bound port.
func TestDevUpRefusesBoundPortReal(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:54318")
	if err != nil {
		t.Skipf("cannot bind 54318 on this host (already in use?): %v", err)
	}
	defer l.Close()
	h := newHarness(t, healthyEnv(), hephToml)
	h.deps.PortInUse = nil // use the real checker
	if code := h.run("dev", "up"); code != 2 {
		t.Fatalf("exit = %d, want 2; stderr=%q", code, h.errb.String())
	}
	msg := h.errb.String()
	if !strings.Contains(msg, "54318") || !strings.Contains(msg, "telemetry") {
		t.Fatalf("stderr must name port 54318 and fragment telemetry: %q", msg)
	}
	if len(h.runner.calls) != 0 {
		t.Fatalf("docker must not run after a failed preflight: %v", h.runner.calls)
	}
}

// Every port of every selected fragment is checked, not one hard-coded port.
func TestDevUpPreflightChecksEveryPort(t *testing.T) {
	for _, tc := range []struct {
		port     int
		fragment string
	}{{54300, "telemetry"}, {54317, "telemetry"}, {54318, "telemetry"}, {54320, "postgres"}} {
		t.Run(fmt.Sprint(tc.port), func(t *testing.T) {
			h := newHarness(t, healthyEnv(), hephToml)
			h.deps.PortInUse = func(p int) bool { return p == tc.port }
			if code := h.run("dev", "up"); code != 2 {
				t.Fatalf("exit = %d, want 2", code)
			}
			msg := h.errb.String()
			if !strings.Contains(msg, fmt.Sprint(tc.port)) || !strings.Contains(msg, tc.fragment) {
				t.Fatalf("stderr = %q", msg)
			}
		})
	}
}

func TestDevUpPortOfUnselectedFragmentIgnored(t *testing.T) {
	h := newHarness(t, healthyEnv(), hephToml) // objects not selected
	h.deps.PortInUse = func(p int) bool { return p == 54333 }
	if code := h.run("dev", "up"); code != 0 {
		t.Fatalf("exit = %d; stderr=%q", code, h.errb.String())
	}
}

func TestDevUpRunsComposeAndPrintsGrafana(t *testing.T) {
	h := newHarness(t, healthyEnv(), hephToml)
	if code := h.run("dev", "up"); code != 0 {
		t.Fatalf("exit = %d; stderr=%q", code, h.errb.String())
	}
	if len(h.runner.calls) != 1 {
		t.Fatalf("calls = %v", h.runner.calls)
	}
	args := h.runner.calls[0]
	joined := strings.Join(args, " ")
	if args[0] != "compose" || !strings.HasPrefix(joined, "compose -p hello -f ") ||
		!strings.HasSuffix(joined, " up -d --wait") {
		t.Fatalf("args = %v", args)
	}
	if !strings.Contains(joined, "telemetry.yaml") || !strings.Contains(joined, "postgres.yaml") ||
		strings.Contains(joined, "objects.yaml") {
		t.Fatalf("wrong files: %v", args)
	}
	if !strings.Contains(h.out.String(), "http://localhost:54300") {
		t.Fatalf("stdout = %q", h.out.String())
	}
	if _, err := os.Stat(filepath.Join(h.state, "hello", "telemetry.yaml")); err != nil {
		t.Fatalf("fragments not materialized under the state dir: %v", err)
	}
}

func TestDevUpSupportFilesMaterialized(t *testing.T) {
	h := newHarness(t, healthyEnv(), "[ingot]\nname = \"hello\"\n[dev]\nfragments = [\"objects\"]\n")
	if code := h.run("dev", "up"); code != 0 {
		t.Fatalf("exit = %d; stderr=%q", code, h.errb.String())
	}
	// objects.yaml bind-mounts ./s.json, so it must sit beside the fragment.
	if _, err := os.Stat(filepath.Join(h.state, "hello", "s.json")); err != nil {
		t.Fatalf("support file missing: %v", err)
	}
	if strings.Contains(h.out.String(), "54300") {
		t.Fatalf("Grafana URL printed without telemetry: %q", h.out.String())
	}
}

func TestDevUpUserErrorsExitOne(t *testing.T) {
	cases := map[string]struct {
		toml string
		want string
	}{
		"missing heph.toml":  {"", "heph.toml"},
		"bad heph.toml":      {"[ingot\n", "heph.toml"},
		"unknown fragment":   {"[ingot]\nname = \"hello\"\n[dev]\nfragments = [\"nope\"]\n", "telemetry"},
		"malformed fragment": {"[ingot]\nname = \"hello\"\n[dev]\nfragments = [\"broken\"]\n", "broken.yaml"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t, healthyEnv(), c.toml)
			if code := h.run("dev", "up"); code != 1 {
				t.Fatalf("exit = %d, want 1; stderr=%q", code, h.errb.String())
			}
			if !strings.Contains(h.errb.String(), c.want) {
				t.Fatalf("stderr = %q, want %q", h.errb.String(), c.want)
			}
			if strings.Contains(h.errb.String(), "goroutine") {
				t.Fatalf("stack trace leaked: %q", h.errb.String())
			}
			if len(h.runner.calls) != 0 {
				t.Fatal("docker must not run")
			}
		})
	}
}

// A wrong heph.toml is the user's mistake (1) even when Docker is also missing.
func TestUserErrorBeatsEnvironmentError(t *testing.T) {
	h := newHarness(t, fakeEnv{onPath: map[string]bool{}}, "[ingot]\nname = \"hello\"\n[dev]\nfragments = [\"nope\"]\n")
	if code := h.run("dev", "up"); code != 1 {
		t.Fatalf("exit = %d, want 1", code)
	}
}

func TestUnknownCommandIsUserError(t *testing.T) {
	h := newHarness(t, healthyEnv(), hephToml)
	if code := h.run("dev", "sideways"); code != 1 {
		t.Fatalf("exit = %d, want 1", code)
	}
}

func TestDevStatusAndDown(t *testing.T) {
	h := newHarness(t, healthyEnv(), hephToml)
	if code := h.run("dev", "status"); code != 0 {
		t.Fatalf("status exit = %d; %q", code, h.errb.String())
	}
	if got := h.runner.calls[0]; got[len(got)-1] != "ps" {
		t.Fatalf("status args = %v", got)
	}
	if code := h.run("dev", "down"); code != 0 {
		t.Fatalf("down exit = %d", code)
	}
	if got := h.runner.calls[1]; got[len(got)-1] != "down" {
		t.Fatalf("down must keep volumes by default: %v", got)
	}
	if code := h.run("dev", "down", "--volumes"); code != 0 {
		t.Fatalf("down --volumes exit = %d", code)
	}
	got := h.runner.calls[2]
	if got[len(got)-2] != "down" || got[len(got)-1] != "-v" {
		t.Fatalf("down --volumes args = %v", got)
	}
}

func TestDevDownWithoutDockerIsEnvironmentError(t *testing.T) {
	h := newHarness(t, fakeEnv{onPath: map[string]bool{}}, hephToml)
	if code := h.run("dev", "down"); code != 2 {
		t.Fatalf("exit = %d, want 2", code)
	}
}

func TestVersion(t *testing.T) {
	h := newHarness(t, fakeEnv{}, "")
	if code := h.run("version"); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	if !strings.HasPrefix(h.out.String(), "heph ") || !strings.Contains(h.out.String(), "experimental") {
		t.Fatalf("stdout = %q", h.out.String())
	}
}
