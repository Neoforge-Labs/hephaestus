// Package cli implements the heph command line. Maturity: experimental.
package cli

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"time"

	"github.com/spf13/cobra"

	"github.com/Neoforge-Labs/hephaestus/go/internal/compose"
	"github.com/Neoforge-Labs/hephaestus/go/internal/fragments"
)

// Exit codes are part of the CLI contract.
const (
	ExitOK   = 0
	ExitUser = 1 // the user's command, heph.toml or fragment selection is wrong
	ExitEnv  = 2 // the machine is wrong: missing/old Docker, bound port
)

// ExitError carries an exit code out of a command.
type ExitError struct {
	Code int
	Err  error
}

func (e *ExitError) Error() string { return e.Err.Error() }
func (e *ExitError) Unwrap() error { return e.Err }

func envErr(format string, a ...any) error {
	return &ExitError{ExitEnv, fmt.Errorf(format, a...)}
}

// Env is the host toolchain: how heph finds and queries `docker`.
type Env interface {
	LookPath(name string) (string, error)
	Output(ctx context.Context, name string, args ...string) ([]byte, error)
}

// Deps is everything the commands touch outside the process, injected so tests
// need neither a Docker daemon nor the real filesystem layout.
type Deps struct {
	Env       Env
	Runner    compose.Runner
	Fragments fs.FS          // fragment source; nil means the embedded copy
	Dir       string         // the ingot directory (where heph.toml lives)
	StateDir  string         // where fragments are written for Compose
	PortInUse func(int) bool // nil means a real TCP check
	Out, Err  io.Writer
}

// NewRoot builds the command tree.
func NewRoot(d Deps) *cobra.Command {
	root := &cobra.Command{
		Use:           "heph",
		Short:         "Hephaestus: NeoForge Labs' full-stack kit (experimental)",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.SetOut(d.Out)
	root.SetErr(d.Err)
	root.AddCommand(newVersionCmd(d), newDoctorCmd(d), newDevCmd(d), newSyncFragmentsCmd(d))
	return root
}

// Execute runs heph with args and returns the process exit code. Errors are
// printed to d.Err; cobra usage errors are user errors.
func Execute(ctx context.Context, d Deps, args []string) int {
	root := NewRoot(d)
	root.SetArgs(args)
	err := root.ExecuteContext(ctx)
	if err == nil {
		return ExitOK
	}
	fmt.Fprintf(d.Err, "heph: %v\n", err)
	var ee *ExitError
	if errors.As(err, &ee) {
		return ee.Code
	}
	return ExitUser
}

// DefaultDeps wires the real host.
func DefaultDeps() (Deps, error) {
	dir, err := os.Getwd()
	if err != nil {
		return Deps{}, err
	}
	cache, err := os.UserCacheDir()
	if err != nil {
		cache = os.TempDir()
	}
	return Deps{
		Env: hostEnv{}, Runner: compose.ExecRunner{},
		Dir: dir, StateDir: filepath.Join(cache, "heph", "stacks"),
		Out: os.Stdout, Err: os.Stderr,
	}, nil
}

type hostEnv struct{}

func (hostEnv) LookPath(name string) (string, error) { return exec.LookPath(name) }
func (hostEnv) Output(ctx context.Context, name string, args ...string) ([]byte, error) {
	return exec.CommandContext(ctx, name, args...).Output()
}

func (d Deps) fragmentFS() fs.FS {
	if d.Fragments != nil {
		return d.Fragments
	}
	return fragments.Embedded()
}

// portInUse is true when something already listens on the port, on any
// interface Docker would publish to.
func (d Deps) portInUse(p int) bool {
	if d.PortInUse != nil {
		return d.PortInUse(p)
	}
	return tcpPortInUse(p)
}

func tcpPortInUse(p int) bool {
	addr := net.JoinHostPort("127.0.0.1", strconv.Itoa(p))
	if c, err := net.DialTimeout("tcp", addr, 200*time.Millisecond); err == nil {
		_ = c.Close()
		return true
	}
	l, err := net.Listen("tcp", net.JoinHostPort("", strconv.Itoa(p)))
	if err != nil {
		return true
	}
	_ = l.Close()
	return false
}
