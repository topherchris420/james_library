#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum AuthorityTier {
    Operator,
    Analyst,
    ResearchLead,
    Executive,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanonicalAgent {
    James,
    Elena,
    Jasmine,
    Luca,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrganizationAction {
    ReadTelemetry,
    UpdateRunbook,
    TriggerExperiment,
    ApproveDeployment,
    RotateCredentials,
    ModifySecurityPolicy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AgentIdentity {
    pub name: &'static str,
    pub role: &'static str,
    pub title: &'static str,
    pub tier: AuthorityTier,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LabOrganization {
    pub james: AgentIdentity,
    pub elena: AgentIdentity,
    pub jasmine: AgentIdentity,
    pub luca: AgentIdentity,
}

impl Default for LabOrganization {
    fn default() -> Self {
        Self {
            james: AgentIdentity {
                name: "James",
                role: "Program Direction",
                title: "Executive Director",
                tier: AuthorityTier::Executive,
            },
            elena: AgentIdentity {
                name: "Elena",
                role: "Research Governance",
                title: "Research Lead",
                tier: AuthorityTier::ResearchLead,
            },
            jasmine: AgentIdentity {
                name: "Jasmine",
                role: "Data Intelligence",
                title: "Senior Analyst",
                tier: AuthorityTier::Analyst,
            },
            luca: AgentIdentity {
                name: "Luca",
                role: "Operations Execution",
                title: "Operations Operator",
                tier: AuthorityTier::Operator,
            },
        }
    }
}

impl LabOrganization {
    #[must_use]
    pub fn identity(&self, agent: CanonicalAgent) -> &AgentIdentity {
        match agent {
            CanonicalAgent::James => &self.james,
            CanonicalAgent::Elena => &self.elena,
            CanonicalAgent::Jasmine => &self.jasmine,
            CanonicalAgent::Luca => &self.luca,
        }
    }

    #[must_use]
    pub fn can_request(&self, agent: CanonicalAgent, action: OrganizationAction) -> bool {
        let tier = self.identity(agent).tier;

        match action {
            OrganizationAction::ReadTelemetry => tier >= AuthorityTier::Operator,
            OrganizationAction::UpdateRunbook => tier >= AuthorityTier::Analyst,
            OrganizationAction::TriggerExperiment => tier >= AuthorityTier::ResearchLead,
            OrganizationAction::ApproveDeployment => tier >= AuthorityTier::Executive,
            OrganizationAction::RotateCredentials | OrganizationAction::ModifySecurityPolicy => {
                tier >= AuthorityTier::Executive
            }
        }
    }

    #[must_use]
    pub fn requires_human_signature(action: OrganizationAction) -> bool {
        matches!(
            action,
            OrganizationAction::ApproveDeployment
                | OrganizationAction::RotateCredentials
                | OrganizationAction::ModifySecurityPolicy
        )
    }
}

#[cfg(test)]
mod tests {
    use super::{AuthorityTier, CanonicalAgent, LabOrganization, OrganizationAction};

    #[test]
    fn canonical_role_to_tier_mapping_is_stable() {
        let organization = LabOrganization::default();

        assert_eq!(
            organization.identity(CanonicalAgent::James).tier,
            AuthorityTier::Executive
        );
        assert_eq!(
            organization.identity(CanonicalAgent::Elena).tier,
            AuthorityTier::ResearchLead
        );
        assert_eq!(
            organization.identity(CanonicalAgent::Jasmine).tier,
            AuthorityTier::Analyst
        );
        assert_eq!(
            organization.identity(CanonicalAgent::Luca).tier,
            AuthorityTier::Operator
        );
    }

    #[test]
    fn authority_tier_ordering_matches_policy_hierarchy() {
        assert!(AuthorityTier::Operator < AuthorityTier::Analyst);
        assert!(AuthorityTier::Analyst < AuthorityTier::ResearchLead);
        assert!(AuthorityTier::ResearchLead < AuthorityTier::Executive);
    }

    #[test]
    fn high_stakes_actions_require_signature_and_executive_tier() {
        let organization = LabOrganization::default();

        assert!(LabOrganization::requires_human_signature(
            OrganizationAction::ApproveDeployment
        ));
        assert!(LabOrganization::requires_human_signature(
            OrganizationAction::RotateCredentials
        ));
        assert!(LabOrganization::requires_human_signature(
            OrganizationAction::ModifySecurityPolicy
        ));
        assert!(!LabOrganization::requires_human_signature(
            OrganizationAction::ReadTelemetry
        ));

        assert!(
            !organization.can_request(CanonicalAgent::Luca, OrganizationAction::RotateCredentials)
        );
        assert!(!organization.can_request(
            CanonicalAgent::Jasmine,
            OrganizationAction::ApproveDeployment
        ));
        assert!(organization.can_request(
            CanonicalAgent::James,
            OrganizationAction::ModifySecurityPolicy
        ));
    }
}
