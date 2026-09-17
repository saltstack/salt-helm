{{- define "salt-minion-vcf.name" -}}
salt-minion-vcf
{{- end }}

{{- define "salt-minion-vcf.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "salt-minion-vcf.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "salt-minion-vcf.labels" -}}
app.kubernetes.io/name: {{ include "salt-minion-vcf.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{- define "salt-minion-vcf.selectorLabels" -}}
app.kubernetes.io/name: {{ include "salt-minion-vcf.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
