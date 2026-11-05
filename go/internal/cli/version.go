package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

// Version is kept in step with the other lockstep packages by release-please
// (see release-please-config.json). It is overridden at link time: -ldflags "-X .../internal/cli.Version=1.2.3".
var Version = "0.1.0" // x-release-please-version

func newVersionCmd(d Deps) *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print the heph version",
		Args:  cobra.NoArgs,
		RunE: func(*cobra.Command, []string) error {
			_, err := fmt.Fprintf(d.Out, "heph %s (experimental)\n", Version)
			return err
		},
	}
}
