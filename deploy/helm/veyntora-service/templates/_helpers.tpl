{{- define "svc.name" -}}{{- default .Release.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}{{- end -}}
{{- define "svc.labels" -}}
app.kubernetes.io/name: {{ include "svc.name" . }}
app.kubernetes.io/part-of: veyntora
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
{{- end -}}
{{- define "svc.selector" -}}
app.kubernetes.io/name: {{ include "svc.name" . }}
{{- end -}}
{{- define "svc.securityContext" -}}
runAsNonRoot: true
runAsUser: {{ .Values.runAsUser }}
runAsGroup: {{ .Values.runAsUser }}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: { drop: [ALL] }
seccompProfile: { type: RuntimeDefault }
{{- end -}}
{{- define "svc.env" -}}
{{- range $k, $v := .Values.env }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}
