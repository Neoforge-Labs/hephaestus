// Package compose builds `docker compose` argument lists and runs them.
// Maturity: experimental.
package compose

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// Runner executes `docker <args>`. Everything that would shell out goes through
// it so callers can be tested without a Docker daemon.
type Runner interface {
	Run(ctx context.Context, args []string) error
	// Output runs `docker <args>` and returns its stdout, for queries such as
	// `compose ps --format json`.
	Output(ctx context.Context, args []string) ([]byte, error)
}

// Args builds the argument list for `docker`, e.g. for verb "up":
// compose -p <project> -f <file>... up -d --wait.
// `up` always detaches and waits for healthchecks; other verbs get no implicit
// flags. extra is appended after the verb (e.g. "-v" for `down`).
func Args(project string, files []string, verb string, extra ...string) []string {
	args := []string{"compose", "-p", project}
	for _, f := range files {
		args = append(args, "-f", f)
	}
	args = append(args, verb)
	if verb == "up" {
		args = append(args, "-d", "--wait")
	}
	return append(args, extra...)
}

// ExecRunner runs the real docker binary with the process's stdio.
type ExecRunner struct{}

// Run implements Runner.
func (ExecRunner) Run(ctx context.Context, args []string) error {
	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Stdout, cmd.Stderr, cmd.Stdin = os.Stdout, os.Stderr, os.Stdin
	return cmd.Run()
}

// Output implements Runner.
// A failing command's stderr is folded into the error so the cause is legible.
func (ExecRunner) Output(ctx context.Context, args []string) ([]byte, error) {
	out, err := exec.CommandContext(ctx, "docker", args...).Output()
	var ee *exec.ExitError
	if errors.As(err, &ee) {
		if msg := strings.TrimSpace(string(ee.Stderr)); msg != "" {
			return out, fmt.Errorf("%w: %s", err, msg)
		}
	}
	return out, err
}
