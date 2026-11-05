package cli

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"github.com/spf13/cobra"
)

// Minimums: `up --wait` needs Compose v2.1+; Docker 20.10 is the oldest engine
// the v2 plugin supports.
const (
	minDockerMajor, minDockerMinor   = 20, 10
	minComposeMajor, minComposeMinor = 2, 1
)

func newDoctorCmd(d Deps) *cobra.Command {
	return &cobra.Command{
		Use:   "doctor",
		Short: "Check that this machine can run the local stack",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := runDoctor(cmd.Context(), d); err != nil {
				return err
			}
			fmt.Fprintln(d.Out, "ok: environment can run the local stack")
			return nil
		},
	}
}

// runDoctor verifies Docker, Compose v2 and a reachable daemon. Every failure
// is an environment error (exit 2).
func runDoctor(ctx context.Context, d Deps) error {
	if _, err := d.Env.LookPath("docker"); err != nil {
		return envErr("docker not found on PATH: install Docker Desktop or Docker Engine 20.10+ with the Compose v2 plugin")
	}
	out, err := d.Env.Output(ctx, "docker", "version", "--format", "{{.Client.Version}}")
	dv := strings.TrimSpace(string(out))
	// `docker version` exits non-zero when the daemon is down but still prints
	// the client version; only give up if it printed nothing usable.
	if err != nil && dv == "" {
		return envErr("could not read the docker version: %v", err)
	}
	if maj, min, ok := parseVersion(dv); !ok || less(maj, min, minDockerMajor, minDockerMinor) {
		return envErr("docker %q is too old or unrecognised: need 20.10 or newer", dv)
	}
	out, err = d.Env.Output(ctx, "docker", "compose", "version", "--short")
	cv := strings.TrimSpace(string(out))
	if err != nil {
		return envErr("Docker Compose v2 is required (`docker compose`, not `docker-compose`): the plugin is missing (%v)", err)
	}
	if maj, min, ok := parseVersion(cv); !ok || less(maj, min, minComposeMajor, minComposeMinor) {
		return envErr("Docker Compose v2.1 or newer is required, found %q", cv)
	}
	if _, err := d.Env.Output(ctx, "docker", "info", "--format", "{{.ServerVersion}}"); err != nil {
		return envErr("the docker daemon is not reachable: start Docker and retry (%v)", err)
	}
	return nil
}

func less(maj, min, wantMaj, wantMin int) bool {
	return maj < wantMaj || (maj == wantMaj && min < wantMin)
}

// parseVersion reads "v2.29.7", "27.3.1" or "v2.30.0-desktop.1" as (major, minor).
func parseVersion(s string) (major, minor int, ok bool) {
	s = strings.TrimPrefix(strings.TrimSpace(s), "v")
	parts := strings.SplitN(s, ".", 3)
	if len(parts) < 2 {
		return 0, 0, false
	}
	major, err1 := strconv.Atoi(parts[0])
	minor, err2 := strconv.Atoi(parts[1])
	if err1 != nil || err2 != nil {
		return 0, 0, false
	}
	return major, minor, true
}
